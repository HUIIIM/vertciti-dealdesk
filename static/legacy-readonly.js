/* 旧版三页只读冻结：横幅＋输入冻结（2026-11-03 下线） */
(function () {
  var banner = document.createElement('div');
  banner.id = 'legacyBanner';
  banner.innerHTML = '<span style="font-weight:700">旧版只读</span>'
    + '<span>30 天后下线（2026-11-03），请用 <a href="/" style="color:#2dd4bf;font-weight:700">新版 DealDesk</a></span>';
  banner.setAttribute('style', 'position:sticky;top:0;z-index:9999;background:#3a2b00;color:#fbbf24;'
    + 'padding:10px 16px;font-size:13px;display:flex;gap:12px;align-items:center;justify-content:center;'
    + 'border-bottom:1px solid #fbbf24');
  if (document.body) document.body.insertBefore(banner, document.body.firstChild);
  else document.addEventListener('DOMContentLoaded', function () {
    document.body.insertBefore(banner, document.body.firstChild);
  });
  function freeze() {
    document.querySelectorAll('input,select,textarea').forEach(function (el) {
      el.disabled = true;
      el.title = '旧版已冻结为只读，请用新版';
    });
  }
  freeze();
  document.addEventListener('DOMContentLoaded', freeze);
  // 兜底：拦截一切表单提交
  document.addEventListener('submit', function (e) {
    e.preventDefault(); e.stopPropagation();
    alert('旧版已冻结为只读（2026-11-03 下线），请用新版 DealDesk。');
  }, true);
})();
