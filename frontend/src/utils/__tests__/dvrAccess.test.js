import { describe, it, expect } from 'vitest';
import {
  DVR_ACCESS,
  canManageDvr,
  canViewDvr,
  getDvrAccess,
} from '../dvrAccess';
import { USER_LEVELS } from '../../constants';

describe('dvrAccess', () => {
  it('denies missing users', () => {
    expect(getDvrAccess(null)).toBe(DVR_ACCESS.NONE);
    expect(canViewDvr(null)).toBe(false);
    expect(canManageDvr(undefined)).toBe(false);
  });

  it('allows admins as manage', () => {
    const admin = { user_level: USER_LEVELS.ADMIN, custom_properties: {} };
    expect(getDvrAccess(admin)).toBe(DVR_ACCESS.MANAGE);
    expect(canViewDvr(admin)).toBe(true);
    expect(canManageDvr(admin)).toBe(true);
  });

  it('defaults standard users to view', () => {
    const user = { user_level: USER_LEVELS.STANDARD, custom_properties: {} };
    expect(getDvrAccess(user)).toBe(DVR_ACCESS.VIEW);
    expect(canViewDvr(user)).toBe(true);
    expect(canManageDvr(user)).toBe(false);
  });

  it('denies when dvr_access is none', () => {
    const user = {
      user_level: USER_LEVELS.STANDARD,
      custom_properties: { dvr_access: DVR_ACCESS.NONE },
    };
    expect(getDvrAccess(user)).toBe(DVR_ACCESS.NONE);
    expect(canViewDvr(user)).toBe(false);
    expect(canManageDvr(user)).toBe(false);
  });

  it('grants view when dvr_access is view', () => {
    const user = {
      user_level: USER_LEVELS.STANDARD,
      custom_properties: { dvr_access: DVR_ACCESS.VIEW },
    };
    expect(canViewDvr(user)).toBe(true);
    expect(canManageDvr(user)).toBe(false);
  });

  it('grants manage and view when dvr_access is manage', () => {
    const user = {
      user_level: USER_LEVELS.STANDARD,
      custom_properties: { dvr_access: DVR_ACCESS.MANAGE },
    };
    expect(canManageDvr(user)).toBe(true);
    expect(canViewDvr(user)).toBe(true);
  });

  it('denies streamers even when dvr_access is manage', () => {
    const user = {
      user_level: USER_LEVELS.STREAMER,
      custom_properties: { dvr_access: DVR_ACCESS.MANAGE },
    };
    expect(getDvrAccess(user)).toBe(DVR_ACCESS.NONE);
    expect(canViewDvr(user)).toBe(false);
    expect(canManageDvr(user)).toBe(false);
  });
});
