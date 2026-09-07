'use client';

import dynamic from 'next/dynamic';

// MapLibre は window を触るのでサーバ側では描かない
const MapView = dynamic(() => import('@/components/MapView'), { ssr: false });

export default function Page() {
  return <MapView />;
}
