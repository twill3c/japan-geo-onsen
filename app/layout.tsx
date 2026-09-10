import type { Metadata } from 'next';
import './globals.css';
import Footer from '@/components/Footer';
import { DISCLAIMER } from '@/lib/layers';

export const metadata: Metadata = {
  title: '日本列島 自然環境・温泉GIS',
  description:
    '地形・地質・火山・水・温泉を一枚の地図に重ね、公開データの範囲で関係を実測する教育・研究用の Web GIS。',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <header className="site-header">
          <h1>日本列島 自然環境・温泉GIS</h1>
          <nav>
            <a href="/">地図</a>
            <a href="/stats/">温泉と地理環境</a>
            <a href="/onsen-stats/">温泉の統計</a>
            <a href="/missing/">地図に出せない温泉</a>
            <a href="/about/">データと出典</a>
          </nav>
          <span className="sub">地形・地質・火山・水・温泉を重ねて読む</span>
        </header>
        <p className="disclaimer">{DISCLAIMER}</p>
        <main>{children}</main>
        <Footer />
      </body>
    </html>
  );
}
