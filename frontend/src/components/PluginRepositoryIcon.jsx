import React from 'react';
import { GitBranch } from 'lucide-react';
import logo from '../images/logo.png';

export default function PluginRepositoryIcon({ isOfficial, size = 12 }) {
  if (!isOfficial) return <GitBranch size={size} aria-hidden="true" />;

  return (
    <span
      aria-hidden="true"
      data-testid="official-repository-icon"
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        flexShrink: 0,
        backgroundColor: 'currentColor',
        mask: `url(${logo}) center / contain no-repeat`,
        WebkitMask: `url(${logo}) center / contain no-repeat`,
      }}
    />
  );
}
