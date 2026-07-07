(function () {
  function activateIn(container, selector, activeClass, matchAttr, value) {
    container.querySelectorAll(selector).forEach(function (el) {
      el.classList.toggle(activeClass, el.getAttribute(matchAttr) === value);
    });
  }

  document.querySelectorAll('.att-tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
      var key = tab.getAttribute('data-att');
      document.querySelectorAll('.att-tab').forEach(function (t) {
        t.classList.toggle('active', t === tab);
      });
      document.querySelectorAll('.att-panel').forEach(function (p) {
        p.classList.toggle('active', p.getAttribute('data-att') === key);
      });
    });
  });

  document.querySelectorAll('.slides-view').forEach(function (view) {
    function selectSlide(index) {
      activateIn(view, '.slide-thumb', 'active', 'data-index', index);
      activateIn(view, '.slide-figure', 'active', 'data-index', index);
      activateIn(view, '.page-result', 'active', 'data-index', index);
    }

    view.querySelectorAll('.slide-thumb').forEach(function (thumb) {
      thumb.addEventListener('click', function () {
        selectSlide(thumb.getAttribute('data-index'));
      });
    });
  });

  document.querySelectorAll('.excel-view').forEach(function (view) {
    view.querySelectorAll('.sheet-tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        var sheet = tab.getAttribute('data-sheet');
        view.querySelectorAll('.sheet-tab').forEach(function (t) {
          t.classList.toggle('active', t === tab);
        });
        view.querySelectorAll('.sheet-panel').forEach(function (p) {
          p.classList.toggle('active', p.getAttribute('data-sheet') === sheet);
        });
      });
    });
  });
})();
