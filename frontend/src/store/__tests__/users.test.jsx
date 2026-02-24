import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import useUsersStore from '../users';
import api from '../../api';

vi.mock('../../api');

describe('useUsersStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUsersStore.setState({
      users: [],
      isLoading: false,
      error: null,
    });
  });

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useUsersStore());

    expect(result.current.users).toEqual([]);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('should fetch users successfully', async () => {
    const mockUsers = [
      { id: 1, name: 'User 1', email: 'user1@example.com' },
      { id: 2, name: 'User 2', email: 'user2@example.com' },
    ];

    api.getUsers.mockResolvedValue(mockUsers);

    const { result } = renderHook(() => useUsersStore());

    await act(async () => {
      await result.current.fetchUsers();
    });

    expect(api.getUsers).toHaveBeenCalled();
    expect(result.current.users).toEqual(mockUsers);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBe(null);
  });

  it('should handle fetch users error', async () => {
    const mockError = new Error('Network error');
    api.getUsers.mockRejectedValue(mockError);

    const consoleErrorSpy = vi
      .spyOn(console, 'error')
      .mockImplementation(() => {});

    const { result } = renderHook(() => useUsersStore());

    await act(async () => {
      await result.current.fetchUsers();
    });

    expect(result.current.error).toBe('Failed to load users.');
    expect(result.current.isLoading).toBe(false);
    expect(consoleErrorSpy).toHaveBeenCalledWith(
      'Failed to fetch users:',
      mockError
    );

    consoleErrorSpy.mockRestore();
  });

  it('should set loading state during fetch', async () => {
    let resolvePromise;
    const promise = new Promise((resolve) => {
      resolvePromise = resolve;
    });

    api.getUsers.mockReturnValue(promise);

    const { result } = renderHook(() => useUsersStore());

    act(() => {
      result.current.fetchUsers();
    });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.error).toBe(null);

    await act(async () => {
      resolvePromise([]);
      await promise;
    });

    expect(result.current.isLoading).toBe(false);
  });

  it('should add user', () => {
    useUsersStore.setState({
      users: [{ id: 1, name: 'User 1', email: 'user1@example.com' }],
    });

    const { result } = renderHook(() => useUsersStore());
    const newUser = { id: 2, name: 'User 2', email: 'user2@example.com' };

    act(() => {
      result.current.addUser(newUser);
    });

    expect(result.current.users).toEqual([
      { id: 1, name: 'User 1', email: 'user1@example.com' },
      { id: 2, name: 'User 2', email: 'user2@example.com' },
    ]);
  });

  it('should add user to empty users', () => {
    const { result } = renderHook(() => useUsersStore());
    const newUser = { id: 1, name: 'User 1', email: 'user1@example.com' };

    act(() => {
      result.current.addUser(newUser);
    });

    expect(result.current.users).toEqual([newUser]);
  });

  it('should update user', () => {
    useUsersStore.setState({
      users: [
        { id: 1, name: 'User 1', email: 'user1@example.com' },
        { id: 2, name: 'User 2', email: 'user2@example.com' },
      ],
    });

    const { result } = renderHook(() => useUsersStore());
    const updatedUser = {
      id: 1,
      name: 'Updated User',
      email: 'updated@example.com',
    };

    act(() => {
      result.current.updateUser(updatedUser);
    });

    expect(result.current.users).toEqual([
      { id: 1, name: 'Updated User', email: 'updated@example.com' },
      { id: 2, name: 'User 2', email: 'user2@example.com' },
    ]);
  });

  it('should not modify other users when updating', () => {
    useUsersStore.setState({
      users: [
        { id: 1, name: 'User 1', email: 'user1@example.com' },
        { id: 2, name: 'User 2', email: 'user2@example.com' },
      ],
    });

    const { result } = renderHook(() => useUsersStore());
    const updatedUser = {
      id: 1,
      name: 'Updated User',
      email: 'updated@example.com',
    };

    act(() => {
      result.current.updateUser(updatedUser);
    });

    expect(result.current.users[1]).toEqual({
      id: 2,
      name: 'User 2',
      email: 'user2@example.com',
    });
  });

  it('should not modify users when updating non-existent user', () => {
    const initialUsers = [
      { id: 1, name: 'User 1', email: 'user1@example.com' },
      { id: 2, name: 'User 2', email: 'user2@example.com' },
    ];

    useUsersStore.setState({
      users: initialUsers,
    });

    const { result } = renderHook(() => useUsersStore());
    const nonExistentUser = {
      id: 999,
      name: 'Non-existent',
      email: 'none@example.com',
    };

    act(() => {
      result.current.updateUser(nonExistentUser);
    });

    expect(result.current.users).toEqual(initialUsers);
  });

  it('should remove user', () => {
    useUsersStore.setState({
      users: [
        { id: 1, name: 'User 1', email: 'user1@example.com' },
        { id: 2, name: 'User 2', email: 'user2@example.com' },
        { id: 3, name: 'User 3', email: 'user3@example.com' },
      ],
    });

    const { result } = renderHook(() => useUsersStore());

    act(() => {
      result.current.removeUser(2);
    });

    expect(result.current.users).toEqual([
      { id: 1, name: 'User 1', email: 'user1@example.com' },
      { id: 3, name: 'User 3', email: 'user3@example.com' },
    ]);
  });

  it('should handle removing non-existent user', () => {
    const initialUsers = [
      { id: 1, name: 'User 1', email: 'user1@example.com' },
      { id: 2, name: 'User 2', email: 'user2@example.com' },
    ];

    useUsersStore.setState({
      users: initialUsers,
    });

    const { result } = renderHook(() => useUsersStore());

    act(() => {
      result.current.removeUser(999);
    });

    expect(result.current.users).toEqual(initialUsers);
  });

  it('should handle removing from empty users', () => {
    const { result } = renderHook(() => useUsersStore());

    act(() => {
      result.current.removeUser(1);
    });

    expect(result.current.users).toEqual([]);
  });

  it('should handle fetch with empty results', async () => {
    api.getUsers.mockResolvedValue([]);

    const { result } = renderHook(() => useUsersStore());

    await act(async () => {
      await result.current.fetchUsers();
    });

    expect(result.current.users).toEqual([]);
  });

  it('should not modify other users when removing', () => {
    useUsersStore.setState({
      users: [
        { id: 1, name: 'User 1', email: 'user1@example.com' },
        { id: 2, name: 'User 2', email: 'user2@example.com' },
        { id: 3, name: 'User 3', email: 'user3@example.com' },
      ],
    });

    const { result } = renderHook(() => useUsersStore());

    act(() => {
      result.current.removeUser(2);
    });

    expect(result.current.users[0]).toEqual({
      id: 1,
      name: 'User 1',
      email: 'user1@example.com',
    });
    expect(result.current.users[1]).toEqual({
      id: 3,
      name: 'User 3',
      email: 'user3@example.com',
    });
  });
});
