import { useEffect } from 'react';

export default function usePluginPageScrollbarGutter() {
  useEffect(() => {
    document.documentElement.classList.add('plugin-page-scrollbar-gutter');
    return () => document.documentElement.classList.remove('plugin-page-scrollbar-gutter');
  }, []);
}
