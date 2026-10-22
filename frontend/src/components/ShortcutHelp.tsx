import { Dialog, Kbd } from "@/components/ui";
import { GLOBAL_HELP } from "@/lib/hotkeys";

export function ShortcutHelp({ onClose }: { onClose: () => void }) {
  return (
    <Dialog title="键盘快捷键" onClose={onClose}>
      <table className="t" style={{ fontSize: 14 }}>
        <thead><tr><th scope="col">按键</th><th scope="col">作用</th></tr></thead>
        <tbody>{GLOBAL_HELP.map((h) => <tr key={h.combo}><td><Kbd k={h.combo} /></td><td>{h.label}</td></tr>)}</tbody>
      </table>
      <p className="muted" style={{ fontSize: 13 }}>在 Windows / Linux 上 ⌘ 即 Ctrl。焦点在输入框时单字母快捷键不生效，避免抢输入。</p>
    </Dialog>
  );
}
