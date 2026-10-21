/* 旧版三页只读冻结：横幅＋输入冻结（2026-11-03 下线） */
(function () {
  var banner = document.createElement('div');
  banner.id = 'legacyBanner';
  banner.innerHTML = '<span style="font-weight:700">旧版只读</span>'
    + '<span>30 天后下线（2026-11-03），请用 <a href="/" style="color:#C93410;font-weight:700">新版 DealDesk</a></span>';
  banner.setAttribute('style', 'position:sticky;top:0;z-index:9999;background:#FFF4CC;color:#8A5A00;'
    + 'padding:10px 16px;font-size:13px;display:flex;gap:12px;align-items:center;justify-content:center;'
    + 'border-bottom:1px solid #8A5A00');
  if (document.body) document.body.insertBefore(banner, document.body.firstChild);
  else document.addEventListener('DOMContentLoaded', function () {
    document.body.insertBefore(banner, document.body.firstChild);
  });
  function freezeOne(el) {
    el.disabled = true;
    el.title = '旧版已冻结为只读，请用新版';
  }
  function freeze() {
    document.querySelectorAll('input,select,textarea').forEach(freezeOne);
  }
  freeze();
  document.addEventListener('DOMContentLoaded', freeze);
  // 动态渲染的输入（页面 JS 按 schema 后建的表单）在 DOMContentLoaded 后
  // 才出现，静态两遍 freeze 盖不住——MutationObserver 补冻（2026-10-15
  // 台账第 12 项实证：res-legacy 4 个动态 checkbox 曾漏冻）。
  if (window.MutationObserver) {
    var mo = new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        m.addedNodes.forEach(function (n) {
          if (n.nodeType !== 1) return;
          if (/^(INPUT|SELECT|TEXTAREA)$/.test(n.tagName)) freezeOne(n);
          if (n.querySelectorAll) n.querySelectorAll('input,select,textarea').forEach(freezeOne);
        });
      });
    });
    var startObs = function () {
      if (document.body) mo.observe(document.body, { childList: true, subtree: true });
    };
    if (document.body) startObs(); else document.addEventListener('DOMContentLoaded', startObs);
  }
  // 兜底：拦截一切表单提交
  document.addEventListener('submit', function (e) {
    e.preventDefault(); e.stopPropagation();
    alert('旧版已冻结为只读（2026-11-03 下线），请用新版 DealDesk。');
  }, true);
})();
