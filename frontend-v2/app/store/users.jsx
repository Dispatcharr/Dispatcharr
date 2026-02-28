import { create } from "zustand";
import api from "~/lib/api";

const useUsersStore = create((set) => ({
  users: [],
  isLoading: false,
  error: null,

  fetchUsers: async () => {
    set({ isLoading: true, error: null });
    try {
      const users = await api.getUsers();
      set({
        users,
        isLoading: false,
      });
    } catch (error) {
      console.error("Failed to fetch users:", error);
      set({ error: "Failed to load users.", isLoading: false });
    }
  },

  addUser: (user) =>
    set((state) => ({
      users: state.users.concat([user]),
    })),

  updateUser: (updatedUser) =>
    set((state) => ({
      users: state.users.map((user) =>
        user.id === updatedUser.id ? updatedUser : user,
      ),
    })),

  removeUser: (userId) =>
    set((state) => ({
      users: state.users.filter((user) => (user.id === userId ? false : true)),
    })),
}));

export default useUsersStore;
