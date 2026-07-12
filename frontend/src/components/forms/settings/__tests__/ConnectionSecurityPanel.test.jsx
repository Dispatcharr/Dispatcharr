import { render, screen, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ConnectionSecurityPanel from '../ConnectionSecurityPanel';

// ── Store mock ─────────────────────────────────────────────────────────────────
vi.mock('../../../../store/settings.jsx', () => ({ default: vi.fn() }));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Badge: ({ children, color, variant, size }) => (
    <span
      data-testid="badge"
      data-color={color}
      data-variant={variant}
      data-size={size}
    >
      {children}
    </span>
  ),
  Group: ({ children, gap, align }) => (
    <div data-gap={gap} data-align={align}>
      {children}
    </div>
  ),
  Paper: ({ children, p, withBorder }) => (
    <div data-testid="paper" data-p={p} data-with-border={String(withBorder)}>
      {children}
    </div>
  ),
  SimpleGrid: ({ children, spacing }) => (
    <div data-testid="simple-grid" data-spacing={spacing}>
      {children}
    </div>
  ),
  Stack: ({ children, gap }) => <div data-gap={gap}>{children}</div>,
  Text: ({ children, size, c, fw }) => (
    <span data-size={size} data-color={c} data-fw={fw}>
      {children}
    </span>
  ),
  Tooltip: ({ children, label }) => (
    <div data-testid="tooltip" data-tooltip={label}>
      {children}
    </div>
  ),
}));

import useSettingsStore from '../../../../store/settings.jsx';

// ── Helpers ────────────────────────────────────────────────────────────────────

const setupStore = (environment = {}) => {
  vi.mocked(useSettingsStore).mockImplementation((sel) => sel({ environment }));
};

/** Find the service card (Paper) whose subtree contains a Text matching `name` */
const getServiceCard = (name) => {
  const papers = screen.getAllByTestId('paper');
  return papers.find((p) => within(p).queryByText(name));
};

/** Get all badges within a named service card */
const getBadgesIn = (serviceName) =>
  within(getServiceCard(serviceName)).getAllByTestId('badge');

/** Get all tooltips within a named service card */
const getTooltipsIn = (serviceName) =>
  within(getServiceCard(serviceName)).getAllByTestId('tooltip');

/** Find a badge by its exact text content within a service card */
const getBadgeByText = (serviceName, text) =>
  getBadgesIn(serviceName).find((b) => b.textContent === text);

// ──────────────────────────────────────────────────────────────────────────────

describe('ConnectionSecurityPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Top-level rendering ──────────────────────────────────────────────────────

  describe('top-level rendering', () => {
    it('renders the introductory description text', () => {
      setupStore();
      render(<ConnectionSecurityPanel />);
      expect(
        screen.getByText(
          /Encrypt connections to Redis and PostgreSQL using environment variables/i
        )
      ).toBeInTheDocument();
    });

    it('renders both Redis and PostgreSQL service cards', () => {
      setupStore();
      render(<ConnectionSecurityPanel />);
      expect(getServiceCard('Redis')).toBeTruthy();
      expect(getServiceCard('PostgreSQL')).toBeTruthy();
    });
  });

  // ── RedisStatus — TLS disabled ───────────────────────────────────────────────

  describe('RedisStatus — TLS disabled (default)', () => {
    beforeEach(() => {
      setupStore({ redis_tls: { enabled: false } });
      render(<ConnectionSecurityPanel />);
    });

    it('renders all three option labels', () => {
      const card = getServiceCard('Redis');
      expect(within(card).getByText('Encryption')).toBeInTheDocument();
      expect(within(card).getByText('Server Verification')).toBeInTheDocument();
      expect(within(card).getByText('Mutual TLS')).toBeInTheDocument();
    });

    it('shows Encryption badge as "Disabled" with gray color', () => {
      const badge = getBadgeByText('Redis', 'Disabled');
      expect(badge).toBeTruthy();
      expect(badge.dataset.color).toBe('gray');
    });

    it('shows Server Verification badge as "Off" with gray color', () => {
      const card = getServiceCard('Redis');
      const offBadge = within(card)
        .getAllByTestId('badge')
        .find((b) => b.textContent === 'Off');
      expect(offBadge).toBeTruthy();
      expect(offBadge.dataset.color).toBe('gray');
    });

    it('shows Mutual TLS badge as "Inactive" with gray color', () => {
      const badge = getBadgeByText('Redis', 'Inactive');
      expect(badge).toBeTruthy();
      expect(badge.dataset.color).toBe('gray');
    });

    it('shows "not encrypted" tooltip for Encryption', () => {
      const tooltips = getTooltipsIn('Redis');
      expect(
        tooltips.find(
          (t) => t.dataset.tooltip === 'The connection is not encrypted'
        )
      ).toBeTruthy();
    });

    it('shows "Verification is not active" tooltip for Server Verification', () => {
      const tooltips = getTooltipsIn('Redis');
      expect(
        tooltips.find((t) =>
          t.dataset.tooltip?.includes('Verification is not active')
        )
      ).toBeTruthy();
    });

    it('shows "Mutual authentication is not active" tooltip for mTLS', () => {
      const tooltips = getTooltipsIn('Redis');
      expect(
        tooltips.find((t) =>
          t.dataset.tooltip?.includes('Mutual authentication is not active')
        )
      ).toBeTruthy();
    });
  });

  // ── RedisStatus — TLS enabled, verify=true, mtls=false ──────────────────────

  describe('RedisStatus — TLS enabled, verify=true, mtls=false', () => {
    beforeEach(() => {
      setupStore({ redis_tls: { enabled: true, verify: true, mtls: false } });
      render(<ConnectionSecurityPanel />);
    });

    it('shows Encryption badge as "Enabled" with green color', () => {
      const badge = getBadgeByText('Redis', 'Enabled');
      expect(badge).toBeTruthy();
      expect(badge.dataset.color).toBe('green');
    });

    it('shows Server Verification badge as "On" with green color', () => {
      const card = getServiceCard('Redis');
      const onBadge = within(card)
        .getAllByTestId('badge')
        .find((b) => b.textContent === 'On');
      expect(onBadge).toBeTruthy();
      expect(onBadge.dataset.color).toBe('green');
    });

    it('shows Mutual TLS badge as "Inactive" with gray color', () => {
      const badge = getBadgeByText('Redis', 'Inactive');
      expect(badge).toBeTruthy();
      expect(badge.dataset.color).toBe('gray');
    });

    it('shows "connection is encrypted" tooltip for Encryption', () => {
      const tooltips = getTooltipsIn('Redis');
      expect(
        tooltips.find(
          (t) => t.dataset.tooltip === 'The connection is encrypted'
        )
      ).toBeTruthy();
    });

    it('shows "server identity is verified" tooltip for Server Verification', () => {
      const tooltips = getTooltipsIn('Redis');
      expect(
        tooltips.find((t) =>
          t.dataset.tooltip?.includes("server's identity is verified")
        )
      ).toBeTruthy();
    });
  });

  // ── RedisStatus — TLS enabled, verify=false ──────────────────────────────────

  describe('RedisStatus — TLS enabled, verify=false', () => {
    beforeEach(() => {
      setupStore({ redis_tls: { enabled: true, verify: false, mtls: false } });
      render(<ConnectionSecurityPanel />);
    });

    it('shows Server Verification badge as "Off" with yellow color', () => {
      const card = getServiceCard('Redis');
      const offBadge = within(card)
        .getAllByTestId('badge')
        .find((b) => b.textContent === 'Off');
      expect(offBadge).toBeTruthy();
      expect(offBadge.dataset.color).toBe('yellow');
    });

    it('shows "encrypted but server identity is not verified" tooltip', () => {
      const tooltips = getTooltipsIn('Redis');
      expect(
        tooltips.find((t) =>
          t.dataset.tooltip?.includes('server identity is not verified')
        )
      ).toBeTruthy();
    });
  });

  // ── RedisStatus — TLS enabled, mtls=true ─────────────────────────────────────

  describe('RedisStatus — TLS enabled, mtls=true', () => {
    beforeEach(() => {
      setupStore({ redis_tls: { enabled: true, verify: true, mtls: true } });
      render(<ConnectionSecurityPanel />);
    });

    it('shows Mutual TLS badge as "Active" with green color', () => {
      const badge = getBadgeByText('Redis', 'Active');
      expect(badge).toBeTruthy();
      expect(badge.dataset.color).toBe('green');
    });

    it('shows "Both client and server verify each other" tooltip for mTLS', () => {
      const tooltips = getTooltipsIn('Redis');
      expect(
        tooltips.find((t) =>
          t.dataset.tooltip?.includes(
            'Both client and server verify each other'
          )
        )
      ).toBeTruthy();
    });
  });

  // ── RedisStatus — redis_tls undefined ────────────────────────────────────────

  describe('RedisStatus — redis_tls undefined', () => {
    it('falls back to defaults (Disabled/Off/Inactive, all gray)', () => {
      setupStore({});
      render(<ConnectionSecurityPanel />);
      expect(getBadgeByText('Redis', 'Disabled').dataset.color).toBe('gray');
      expect(
        within(getServiceCard('Redis'))
          .getAllByTestId('badge')
          .find((b) => b.textContent === 'Off').dataset.color
      ).toBe('gray');
      expect(getBadgeByText('Redis', 'Inactive').dataset.color).toBe('gray');
    });
  });

  // ── PostgresStatus — TLS disabled ───────────────────────────────────────────

  describe('PostgresStatus — TLS disabled (default)', () => {
    beforeEach(() => {
      setupStore({ postgres_tls: { enabled: false } });
      render(<ConnectionSecurityPanel />);
    });

    it('renders all three option labels', () => {
      const card = getServiceCard('PostgreSQL');
      expect(within(card).getByText('Encryption')).toBeInTheDocument();
      expect(within(card).getByText('Verification Mode')).toBeInTheDocument();
      expect(within(card).getByText('Mutual TLS')).toBeInTheDocument();
    });

    it('shows Encryption badge as "Disabled" with gray color', () => {
      const badge = getBadgeByText('PostgreSQL', 'Disabled');
      expect(badge).toBeTruthy();
      expect(badge.dataset.color).toBe('gray');
    });

    it('shows Verification Mode badge as "Off" with gray color', () => {
      const card = getServiceCard('PostgreSQL');
      const offBadge = within(card)
        .getAllByTestId('badge')
        .find((b) => b.textContent === 'Off');
      expect(offBadge).toBeTruthy();
      expect(offBadge.dataset.color).toBe('gray');
    });

    it('shows Mutual TLS badge as "Inactive" with gray color', () => {
      const badge = getBadgeByText('PostgreSQL', 'Inactive');
      expect(badge).toBeTruthy();
      expect(badge.dataset.color).toBe('gray');
    });

    it('shows "Verification mode is not active" tooltip when TLS is disabled', () => {
      const tooltips = getTooltipsIn('PostgreSQL');
      expect(
        tooltips.find((t) =>
          t.dataset.tooltip?.includes('Verification mode is not active')
        )
      ).toBeTruthy();
    });
  });

  // ── PostgresStatus — ssl_mode=verify-full ───────────────────────────────────

  describe('PostgresStatus — ssl_mode=verify-full', () => {
    beforeEach(() => {
      setupStore({
        postgres_tls: { enabled: true, ssl_mode: 'verify-full', mtls: false },
      });
      render(<ConnectionSecurityPanel />);
    });

    it('shows Verification Mode badge as "verify-full" with green color', () => {
      const badge = getBadgeByText('PostgreSQL', 'verify-full');
      expect(badge).toBeTruthy();
      expect(badge.dataset.color).toBe('green');
    });

    it('shows "Server certificate and hostname are both verified" tooltip', () => {
      const tooltips = getTooltipsIn('PostgreSQL');
      expect(
        tooltips.find((t) =>
          t.dataset.tooltip?.includes(
            'Server certificate and hostname are both verified'
          )
        )
      ).toBeTruthy();
    });
  });

  // ── PostgresStatus — ssl_mode=verify-ca ─────────────────────────────────────

  describe('PostgresStatus — ssl_mode=verify-ca', () => {
    beforeEach(() => {
      setupStore({
        postgres_tls: { enabled: true, ssl_mode: 'verify-ca', mtls: false },
      });
      render(<ConnectionSecurityPanel />);
    });

    it('shows Verification Mode badge as "verify-ca" with yellow color', () => {
      const badge = getBadgeByText('PostgreSQL', 'verify-ca');
      expect(badge).toBeTruthy();
      expect(badge.dataset.color).toBe('yellow');
    });

    it('shows "hostname is not checked" tooltip', () => {
      const tooltips = getTooltipsIn('PostgreSQL');
      expect(
        tooltips.find((t) =>
          t.dataset.tooltip?.includes('hostname is not checked')
        )
      ).toBeTruthy();
    });
  });

  // ── PostgresStatus — ssl_mode=require (other/fallback) ──────────────────────

  describe('PostgresStatus — ssl_mode=require (other)', () => {
    beforeEach(() => {
      setupStore({
        postgres_tls: { enabled: true, ssl_mode: 'require', mtls: false },
      });
      render(<ConnectionSecurityPanel />);
    });

    it('shows Verification Mode badge as "require" with yellow color', () => {
      const badge = getBadgeByText('PostgreSQL', 'require');
      expect(badge).toBeTruthy();
      expect(badge.dataset.color).toBe('yellow');
    });

    it('shows "encrypted but the server is not verified" tooltip', () => {
      const tooltips = getTooltipsIn('PostgreSQL');
      expect(
        tooltips.find((t) =>
          t.dataset.tooltip?.includes('server is not verified')
        )
      ).toBeTruthy();
    });
  });

  // ── PostgresStatus — TLS enabled, ssl_mode absent ───────────────────────────

  describe('PostgresStatus — TLS enabled, ssl_mode absent', () => {
    it('shows Verification Mode badge as "Off" with gray color', () => {
      setupStore({ postgres_tls: { enabled: true, mtls: false } });
      render(<ConnectionSecurityPanel />);
      const card = getServiceCard('PostgreSQL');
      const offBadge = within(card)
        .getAllByTestId('badge')
        .find((b) => b.textContent === 'Off');
      expect(offBadge).toBeTruthy();
      expect(offBadge.dataset.color).toBe('gray');
    });
  });

  // ── PostgresStatus — mtls=true ───────────────────────────────────────────────

  describe('PostgresStatus — mtls=true', () => {
    beforeEach(() => {
      setupStore({
        postgres_tls: { enabled: true, ssl_mode: 'verify-full', mtls: true },
      });
      render(<ConnectionSecurityPanel />);
    });

    it('shows Mutual TLS badge as "Active" with green color', () => {
      const badge = getBadgeByText('PostgreSQL', 'Active');
      expect(badge).toBeTruthy();
      expect(badge.dataset.color).toBe('green');
    });

    it('shows "Both client and server verify each other" tooltip for mTLS', () => {
      const tooltips = getTooltipsIn('PostgreSQL');
      expect(
        tooltips.find((t) =>
          t.dataset.tooltip?.includes(
            'Both client and server verify each other'
          )
        )
      ).toBeTruthy();
    });
  });

  // ── PostgresStatus — mtls=false while TLS enabled ───────────────────────────

  describe('PostgresStatus — mtls=false while TLS enabled', () => {
    it('shows Mutual TLS badge as "Inactive" with gray color', () => {
      setupStore({
        postgres_tls: { enabled: true, ssl_mode: 'verify-full', mtls: false },
      });
      render(<ConnectionSecurityPanel />);
      const badge = getBadgeByText('PostgreSQL', 'Inactive');
      expect(badge).toBeTruthy();
      expect(badge.dataset.color).toBe('gray');
    });

    it('shows "Mutual authentication is not active" tooltip', () => {
      setupStore({
        postgres_tls: { enabled: true, ssl_mode: 'verify-full', mtls: false },
      });
      render(<ConnectionSecurityPanel />);
      const tooltips = getTooltipsIn('PostgreSQL');
      expect(
        tooltips.find((t) =>
          t.dataset.tooltip?.includes('Mutual authentication is not active')
        )
      ).toBeTruthy();
    });
  });

  // ── PostgresStatus — postgres_tls undefined ──────────────────────────────────

  describe('PostgresStatus — postgres_tls undefined', () => {
    it('falls back to all defaults (Disabled/Off/Inactive, all gray)', () => {
      setupStore({});
      render(<ConnectionSecurityPanel />);
      expect(getBadgeByText('PostgreSQL', 'Disabled').dataset.color).toBe(
        'gray'
      );
      expect(
        within(getServiceCard('PostgreSQL'))
          .getAllByTestId('badge')
          .find((b) => b.textContent === 'Off').dataset.color
      ).toBe('gray');
      expect(getBadgeByText('PostgreSQL', 'Inactive').dataset.color).toBe(
        'gray'
      );
    });
  });

  // ── Both services — independent state ────────────────────────────────────────

  describe('both services — independent badge state', () => {
    it('Redis and PostgreSQL badges reflect their own configs independently', () => {
      setupStore({
        redis_tls: { enabled: true, verify: false, mtls: true },
        postgres_tls: { enabled: false },
      });
      render(<ConnectionSecurityPanel />);

      // Redis: enabled → green Enabled, verify=false → yellow Off, mtls=true → green Active
      expect(getBadgeByText('Redis', 'Enabled').dataset.color).toBe('green');
      expect(
        within(getServiceCard('Redis'))
          .getAllByTestId('badge')
          .find((b) => b.textContent === 'Off').dataset.color
      ).toBe('yellow');
      expect(getBadgeByText('Redis', 'Active').dataset.color).toBe('green');

      // Postgres: disabled → all gray/Off/Inactive
      expect(getBadgeByText('PostgreSQL', 'Disabled').dataset.color).toBe(
        'gray'
      );
      expect(
        within(getServiceCard('PostgreSQL'))
          .getAllByTestId('badge')
          .find((b) => b.textContent === 'Off').dataset.color
      ).toBe('gray');
      expect(getBadgeByText('PostgreSQL', 'Inactive').dataset.color).toBe(
        'gray'
      );
    });
  });

  // ── TlsOption description text ────────────────────────────────────────────────

  describe('TlsOption description text', () => {
    beforeEach(() => {
      setupStore({
        redis_tls: { enabled: true, verify: true, mtls: true },
        postgres_tls: { enabled: true, ssl_mode: 'verify-full', mtls: true },
      });
      render(<ConnectionSecurityPanel />);
    });

    it('renders Redis Encryption description', () => {
      expect(
        within(getServiceCard('Redis')).getByText(
          'Encrypt traffic between Dispatcharr and Redis.'
        )
      ).toBeInTheDocument();
    });

    it('renders Redis Server Verification description', () => {
      expect(
        within(getServiceCard('Redis')).getByText(
          "Verify the Redis server's identity using a CA certificate."
        )
      ).toBeInTheDocument();
    });

    it('renders Redis Mutual TLS description', () => {
      expect(
        within(getServiceCard('Redis')).getByText(
          'Authenticate Dispatcharr to Redis using a client certificate.'
        )
      ).toBeInTheDocument();
    });

    it('renders PostgreSQL Encryption description', () => {
      expect(
        within(getServiceCard('PostgreSQL')).getByText(
          'Encrypt traffic between Dispatcharr and PostgreSQL.'
        )
      ).toBeInTheDocument();
    });

    it('renders PostgreSQL Verification Mode description', () => {
      expect(
        within(getServiceCard('PostgreSQL')).getByText(
          "How strictly to verify the PostgreSQL server's identity."
        )
      ).toBeInTheDocument();
    });

    it('renders PostgreSQL Mutual TLS description', () => {
      expect(
        within(getServiceCard('PostgreSQL')).getByText(
          'Authenticate Dispatcharr to PostgreSQL using a client certificate.'
        )
      ).toBeInTheDocument();
    });
  });
});
