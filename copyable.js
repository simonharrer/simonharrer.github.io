(function () {
  var checkSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="#28a745" viewBox="0 0 16 16"><path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/></svg>';

  function copyFromTarget(id) {
    var el = document.getElementById(id);
    if (!el) return Promise.reject();
    var text;
    if (el.tagName === 'INPUT') {
      text = el.value;
    } else {
      var visible = el.querySelector('[data-lang]:not([hidden])');
      text = (visible || el).innerText;
    }
    return navigator.clipboard.writeText(text.trim());
  }

  document.querySelectorAll('[data-copy-target]').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      copyFromTarget(btn.dataset.copyTarget).then(function () {
        var original = btn.innerHTML;
        btn.innerHTML = checkSvg;
        setTimeout(function () { btn.innerHTML = original; }, 1500);
      });
    });
  });

  document.querySelectorAll('[data-copy-card]').forEach(function (card) {
    card.addEventListener('click', function (e) {
      if (e.target.closest('[data-copy-target]')) return;
      var sel = window.getSelection && window.getSelection().toString();
      if (sel && sel.length > 0) return;
      var input = e.target.closest('input');
      if (input && input.selectionStart !== input.selectionEnd) return;
      copyFromTarget(card.dataset.copyCard).then(function () {
        card.classList.add('copy-flash');
        setTimeout(function () { card.classList.remove('copy-flash'); }, 600);
      });
    });
  });

  window.copyFromTarget = copyFromTarget;
})();
