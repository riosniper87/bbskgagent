(function () {
  const form = document.getElementById("qa-form");
  const questionEl = document.getElementById("qa-question");
  const damdangEl = document.getElementById("qa-damdang");
  const queryDateEl = document.getElementById("qa-query-date");
  const loadingEl = document.getElementById("qa-loading");
  const answerBlock = document.getElementById("qa-answer");
  const answerBody = document.getElementById("qa-answer-body");
  const citationsEl = document.getElementById("qa-citations");
  const attachmentsEl = document.getElementById("qa-attachments");
  const hitsEl = document.getElementById("qa-hits");
  const tracesEl = document.getElementById("qa-traces");
  const suggestBtn = document.getElementById("qa-suggest");
  const suggestHint = document.getElementById("qa-suggest-hint");
  const searchOnlyBtn = document.getElementById("qa-search-only");
  const indexStatusEl = document.getElementById("qa-index-status");
  let anchorPostId = null;
  let anchorSourceRef = null;

  const cfg = window.QA_CONFIG || {};

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function renderTraces(traces) {
    tracesEl.innerHTML = "";
    (traces || []).forEach(function (t) {
      const div = document.createElement("div");
      div.className = "qa-trace-item";
      div.innerHTML =
        "<strong>" + esc(t.tool) + "</strong> (" + (t.ms || 0) + "ms)" +
        "<pre>in: " + esc(JSON.stringify(t.input, null, 0)) + "</pre>" +
        "<pre>out: " + esc(JSON.stringify(t.output, null, 0)) + "</pre>";
      tracesEl.appendChild(div);
    });
  }

  function renderHits(hits) {
    hitsEl.innerHTML = (hits || [])
      .map(function (h) {
        const nk = (h.temporal && h.temporal.notice_kind) ? h.temporal.notice_kind : "";
        return "<li class=\"qa-hit-item\">" +
          "<strong>" + esc(h.headline) + "</strong> " +
          "[" + esc(h.damdang) + "] " +
          "score=" + esc(h.score) +
          (nk ? " · " + esc(nk) : "") +
          "<br><span class=\"qa-hit-meta\">" +
          esc(h.source_ref) + " · " + esc(h.attachment_name) +
          "</span> " +
          '<a href="' + esc(h.post_url) + '">게시물</a>' +
          "</li>";
      })
      .join("");
  }

  function formatErrorDetail(detail) {
    if (!detail) return "요청 처리 실패";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map(function (d) {
        if (typeof d === "object" && d !== null) {
          return d.msg || JSON.stringify(d);
        }
        return String(d);
      }).join("; ");
    }
    if (typeof detail === "object") {
      return detail.msg || JSON.stringify(detail);
    }
    return String(detail);
  }

  async function loadStatus() {
    if (!indexStatusEl) return;
    try {
      const res = await fetch("/api/qa/status");
      const data = await res.json();
      if (!res.ok) throw new Error(formatErrorDetail(data.detail));
      const idx = data.index_loaded
        ? "인덱스: " + data.index_card_count + " cards (" + (data.search_pipeline || "v2") + ")"
        : "인덱스: 미로드 (per-query fallback)";
      indexStatusEl.textContent =
        idx + " · corpus " + (data.corpus_card_count || 0) + " cards";
    } catch (err) {
      indexStatusEl.textContent = "상태 로드 실패: " + err.message;
    }
  }

  loadStatus();

  if (suggestBtn) {
    suggestBtn.addEventListener("click", async function () {
      suggestBtn.disabled = true;
      const prevLabel = suggestBtn.textContent;
      suggestBtn.textContent = "생성 중…";
      suggestHint.classList.add("hidden");

      try {
        const res = await fetch("/api/qa/suggest-question", { method: "POST" });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(formatErrorDetail(data.detail) || res.statusText);
        }
        questionEl.value = data.question || "";
        anchorPostId = data.post_id || null;
        anchorSourceRef = data.source_ref || null;
        suggestHint.innerHTML =
          "출처: <a href=\"" + esc(data.post_url) + "\">" + esc(data.post_title) +
          "</a> · " + esc(data.source_label) +
          "<br><span class=\"qa-suggest-excerpt\">" + esc(data.excerpt_preview || "") + "</span>";
        suggestHint.classList.remove("hidden");
        questionEl.focus();
      } catch (err) {
        suggestHint.textContent = "샘플 질문 생성 실패: " + err.message;
        suggestHint.classList.remove("hidden");
      } finally {
        suggestBtn.disabled = false;
        suggestBtn.textContent = prevLabel;
      }
    });
  }

  async function runSearchOnly() {
    const question = questionEl.value.trim();
    if (!question) return;

    loadingEl.textContent = "검색 중… (BM25 + soft boost)";
    loadingEl.classList.remove("hidden");
    answerBlock.classList.add("hidden");

    const body = {
      question: question,
      as_of: cfg.as_of,
      damdang: damdangEl.value || null,
      query_date: queryDateEl.value || null,
      limit: 10,
    };

    try {
      const res = await fetch("/api/qa/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(formatErrorDetail(data.detail) || res.statusText);
      }

      answerBody.textContent =
        "검색만 모드 — " + (data.hits || []).length + "건" +
        (data.index_loaded ? " (persistent index)" : " (fallback BM25)");
      citationsEl.innerHTML = "";
      attachmentsEl.innerHTML = "";
      renderHits(data.hits);
      renderTraces(data.traces);
      answerBlock.classList.remove("hidden");
    } catch (err) {
      answerBody.textContent = "오류: " + err.message;
      answerBlock.classList.remove("hidden");
      tracesEl.innerHTML = "";
    } finally {
      loadingEl.classList.add("hidden");
      loadingEl.textContent = "처리 중…";
    }
  }

  if (searchOnlyBtn) {
    searchOnlyBtn.addEventListener("click", function (e) {
      e.preventDefault();
      runSearchOnly();
    });
  }

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    const question = questionEl.value.trim();
    if (!question) return;

    loadingEl.textContent = "처리 중… (intent → 담당 → 시기 → 검색 → 답변)";
    loadingEl.classList.remove("hidden");
    answerBlock.classList.add("hidden");

    const body = {
      question: question,
      as_of: cfg.as_of,
      damdang: damdangEl.value || null,
      query_date: queryDateEl.value || null,
      anchor_post_id: anchorPostId,
      anchor_source_ref: anchorSourceRef,
    };

    try {
      const res = await fetch("/api/qa/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        const msg = formatErrorDetail(data.detail) || res.statusText;
        throw new Error(msg);
      }

      answerBody.textContent = data.answer || "";
      citationsEl.innerHTML = (data.citations || [])
        .map(function (c) {
          return "<li>" + esc(c.headline) + " — " + esc(c.post_title) +
            " (" + esc(c.attachment_name) + ")</li>";
        })
        .join("");

      attachmentsEl.innerHTML = (data.attachments || [])
        .map(function (a) {
          return '<li><a href="' + esc(a.post_url) + '">' +
            esc(a.attachment_name) + "</a> — " + esc(a.post_title) + "</li>";
        })
        .join("");

      renderHits(data.hits);
      renderTraces(data.traces);
      answerBlock.classList.remove("hidden");
    } catch (err) {
      answerBody.textContent = "오류: " + err.message;
      answerBlock.classList.remove("hidden");
      tracesEl.innerHTML = "";
    } finally {
      loadingEl.classList.add("hidden");
      loadingEl.textContent = "처리 중…";
    }
  });
})();
