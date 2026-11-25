import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import PluginRepositoryIcon from '../PluginRepositoryIcon.jsx';

describe('PluginRepositoryIcon', () => {
  it('uses the monochrome logo for official repositories', () => {
    render(<PluginRepositoryIcon isOfficial />);
    expect(screen.getByTestId('official-repository-icon').style.backgroundColor).toBe('currentcolor');
  });

  it('uses the branch icon for community repositories', () => {
    const { container } = render(<PluginRepositoryIcon isOfficial={false} />);
    expect(container.querySelector('.lucide-git-branch')).toBeInTheDocument();
    expect(screen.queryByTestId('official-repository-icon')).not.toBeInTheDocument();
  });
});
