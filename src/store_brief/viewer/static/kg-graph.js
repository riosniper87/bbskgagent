/* Knowledge graph — Obsidian-style force-directed view (vis-network). */
(function () {
  const COLORS = {
    Post: "#5b9bd5",
    Attachment: "#9b7ede",
    ContentSlice: "#8a8a8a",
    WikiCard: "#e8b339",
    Product: "#5cb87a",
    Damdang: "#e06c75",
  };

  const networkEl = document.getElementById("kg-network");
  const statusEl = document.getElementById("kg-status");
  const panel = document.getElementById("kg-panel");
  const panelTitle = document.getElementById("kg-panel-title");
  const panelBody = document.getElementById("kg-panel-body");
  const panelLinks = document.getElementById("kg-panel-links");
  const legendEl = document.getElementById("kg-legend");

  let network = null;
  let rawNodes = [];
  let rawEdges = [];

  function buildLegend(groups) {
    legendEl.innerHTML = "";
    (groups || Object.keys(COLORS)).forEach((g) => {
      const item = document.createElement("span");
      item.className = "kg-legend-item";
      item.innerHTML =
        '<span class="kg-legend-dot" style="background:' +
        (COLORS[g] || "#aaa") +
        '"></span>' +
        g;
      legendEl.appendChild(item);
    });
  }

  function queryParams() {
    const mode = document.getElementById("kg-mode").value;
    const damdang = document.getElementById("kg-damdang").value;
    const products = document.getElementById("kg-products").checked;
    const coOccurs = document.getElementById("kg-co-occurs").checked;
    const p = new URLSearchParams({ mode });
    if (damdang) p.set("damdang", damdang);
    if (products) p.set("include_products", "1");
    if (coOccurs) p.set("include_co_occurs", "1");
    return p;
  }

  async function loadGraph() {
    statusEl.textContent = "로딩 중…";
    const res = await fetch("/api/kg/graph?" + queryParams().toString());
    if (!res.ok) {
      const err = await res.text();
      statusEl.textContent = "오류: " + res.status + " — " + err;
      return;
    }
    const data = await res.json();
    rawNodes = data.nodes;
    rawEdges = data.edges;
    buildLegend(data.meta && data.meta.groups);
    renderNetwork(rawNodes, rawEdges);
    statusEl.textContent =
      "노드 " +
      data.meta.node_count +
      " · 엣지 " +
      data.meta.edge_count +
      (data.meta.damdang ? " · " + data.meta.damdang : "");
  }

  function renderNetwork(nodes, edges) {
    const data = {
      nodes: new vis.DataSet(nodes),
      edges: new vis.DataSet(edges),
    };
    const options = {
      nodes: {
        shape: "dot",
        borderWidth: 1,
        borderWidthSelected: 3,
        font: { color: "#cdd6f4", strokeWidth: 3, strokeColor: "#1e1e2e" },
        shadow: true,
      },
      edges: {
        smooth: { type: "continuous", roundness: 0.2 },
        color: { inherit: false },
      },
      physics: {
        enabled: true,
        solver: "forceAtlas2Based",
        forceAtlas2Based: {
          gravitationalConstant: -40,
          centralGravity: 0.008,
          springLength: 120,
          springConstant: 0.04,
          damping: 0.5,
        },
        stabilization: { iterations: 150, updateInterval: 25 },
      },
      interaction: {
        hover: true,
        tooltipDelay: 120,
        multiselect: false,
        navigationButtons: true,
        keyboard: { enabled: true },
      },
      layout: { improvedLayout: true },
    };

    if (network) {
      network.setData(data);
      network.setOptions(options);
    } else {
      network = new vis.Network(networkEl, data, options);
      network.on("click", onNodeClick);
      network.on("doubleClick", onNodeDoubleClick);
    }
    network.once("stabilizationIterationsDone", function () {
      network.setOptions({ physics: { enabled: true } });
    });
  }

  function findNode(id) {
    return rawNodes.find((n) => n.id === id);
  }

  function onNodeClick(params) {
    if (!params.nodes.length) {
      panel.classList.add("hidden");
      return;
    }
    const id = params.nodes[0];
    const node = findNode(id);
    if (!node) return;
    panel.classList.remove("hidden");
    panelTitle.textContent = node.label || id;
    panelBody.textContent = (node.title || "").replace(/\\n/g, "\n");
    panelLinks.innerHTML = "";

    if (id.startsWith("card:")) {
      const cardId = id.slice(5);
      fetch("/api/kg/nodes/" + encodeURIComponent(id))
        .then((r) => r.json())
        .then((detail) => {
          const prov = (detail.props && detail.props.provenance) || {};
          if (prov.post_id) {
            addLink("/post/" + prov.post_id, "게시물 보기");
          }
          if (prov.attachment_name) {
            const p = document.createElement("p");
            p.style.fontSize = "0.8rem";
            p.style.color = "#a6adc8";
            p.textContent = "첨부: " + prov.attachment_name;
            panelLinks.appendChild(p);
          }
        })
        .catch(() => {});
    } else if (id.startsWith("post:")) {
      addLink("/post/" + id.slice(5), "게시물 보기");
    } else if (id.startsWith("prd:")) {
      addLink(
        "/api/kg/products/" + encodeURIComponent(id.slice(4)),
        "관련 카드 API"
      );
    }
  }

  function addLink(href, text) {
    const a = document.createElement("a");
    a.href = href;
    a.textContent = text;
    if (href.startsWith("/api/")) a.target = "_blank";
    panelLinks.appendChild(a);
  }

  function onNodeDoubleClick(params) {
    if (params.nodes.length) {
      network.focus(params.nodes[0], {
        scale: 1.4,
        animation: { duration: 400, easingFunction: "easeInOutQuad" },
      });
    }
  }

  function filterSearch() {
    const q = document.getElementById("kg-search").value.trim().toLowerCase();
    if (!network || !q) {
      if (network) {
        rawNodes.forEach((n) => {
          network.body.data.nodes.update({
            id: n.id,
            hidden: false,
            opacity: 1,
          });
        });
      }
      return;
    }
    const matched = new Set();
    rawNodes.forEach((n) => {
      const hay = (n.label + " " + (n.title || "") + " " + n.id).toLowerCase();
      if (hay.includes(q)) matched.add(n.id);
    });
    const neighbor = new Set(matched);
    rawEdges.forEach((e) => {
      if (matched.has(e.from)) neighbor.add(e.to);
      if (matched.has(e.to)) neighbor.add(e.from);
    });
    rawNodes.forEach((n) => {
      const hit = neighbor.has(n.id);
      network.body.data.nodes.update({
        id: n.id,
        hidden: !hit && matched.size > 0,
        opacity: matched.has(n.id) ? 1 : hit ? 0.45 : 0.12,
      });
    });
  }

  document.getElementById("kg-reload").addEventListener("click", loadGraph);
  document.getElementById("kg-mode").addEventListener("change", loadGraph);
  document.getElementById("kg-damdang").addEventListener("change", loadGraph);
  document.getElementById("kg-products").addEventListener("change", loadGraph);
  document.getElementById("kg-co-occurs").addEventListener("change", loadGraph);
  document.getElementById("kg-search").addEventListener("input", filterSearch);
  document.getElementById("kg-panel-close").addEventListener("click", () => {
    panel.classList.add("hidden");
    network.unselectAll();
  });

  if (!window.KG_CONFIG || !window.KG_CONFIG.asOf) {
    statusEl.textContent =
      "as_of 없음 — 서버를 --as-of 2026-06-17 로 실행하세요.";
  } else {
    loadGraph();
  }
})();
