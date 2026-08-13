import { create } from 'zustand';

const useMacDevicesStore = create((set) => ({
  devices: [],
  isLoading: false,
  error: null,

  setDevices: (devices) => set({ devices, isLoading: false }),

  addDevice: (device) =>
    set((state) => ({
      devices: state.devices.concat([device]),
    })),

  updateDevice: (updatedDevice) =>
    set((state) => ({
      devices: state.devices.map((device) =>
        device.id === updatedDevice.id ? updatedDevice : device
      ),
    })),

  removeDevice: (deviceId) =>
    set((state) => ({
      devices: state.devices.filter((device) => device.id !== deviceId),
    })),
}));

export default useMacDevicesStore;
