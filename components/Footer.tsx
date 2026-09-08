/** フリート共通フッタ(koho-lens 準拠・5 項目・下部固定)。 */
export default function Footer() {
  return (
    <footer className="fleet-footer">
      <span>MIT License © 2026 坂田哲朗</span>
      <span>・</span>
      <a href="https://github.com/twill3c/japan-geo-onsen" target="_blank" rel="noreferrer">GitHub</a>
      <span>・</span>
      <a href="/about/">データと出典</a>
      <span>・</span>
      <a href="/onsen-stats/">温泉の統計</a>
      <span>・</span>
      <a href="https://app-menu-nine.vercel.app/" target="_blank" rel="noreferrer">App Menu</a>
    </footer>
  );
}
