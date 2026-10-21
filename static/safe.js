// 安全渲染工具：替代直接拼接 innerHTML。用法：el.innerHTML = html`<b>${userText}</b>`; 插值自动转义。
(function (g) {
  var M = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  function esc(v) { return v == null ? "" : String(v).replace(/[&<>"']/g, function (c) { return M[c]; }); }
  function raw(s) { return { __raw: String(s) }; }
  function html(strings) { var out = strings[0]; for (var i = 1; i < arguments.length; i++) { var v = arguments[i]; out += (v && v.__raw !== undefined ? v.__raw : esc(v)) + strings[i]; } return out; }
  g.vcSafe = { esc: esc, raw: raw, html: html };
})(window);
