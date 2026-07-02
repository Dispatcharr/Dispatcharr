import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();
});

if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

if (typeof window !== 'undefined' && !window.ResizeObserver) {
  class ResizeObserver {
    constructor(callback) {
      this.callback = callback;
    }
    observe() {}
    unobserve() {}
    disconnect() {}
  }

  window.ResizeObserver = ResizeObserver;
}

// Node 25+ exposes a broken native localStorage stub on globalThis (missing
// Storage methods) that shadows jsdom's implementation.
if (typeof window !== 'undefined') {
  const brokenTargets = [globalThis, window].filter(
    (target) => typeof target?.localStorage?.getItem !== 'function'
  );

  if (brokenTargets.length > 0) {
    let store = {};
    const storage = {
      getItem: (key) => store[key] ?? null,
      setItem: (key, value) => {
        store[key] = String(value);
      },
      removeItem: (key) => {
        delete store[key];
      },
      clear: () => {
        store = {};
      },
      get length() {
        return Object.keys(store).length;
      },
      key: (i) => Object.keys(store)[i] ?? null,
    };

    for (const target of brokenTargets) {
      Object.defineProperty(target, 'localStorage', {
        configurable: true,
        enumerable: true,
        writable: true,
        value: storage,
      });
    }
  }
}

if (typeof window !== 'undefined') {
  if (!window.requestAnimationFrame) {
    window.requestAnimationFrame = (cb) => setTimeout(cb, 16);
  }
  if (!window.cancelAnimationFrame) {
    window.cancelAnimationFrame = (id) => clearTimeout(id);
  }
}
