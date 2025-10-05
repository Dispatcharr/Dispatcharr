import React, { createContext, useContext, useMemo, useCallback, useRef } from 'react';
import API from '../api';
import usePluginsStore from '../store/plugins';

const PluginUIContext = createContext(null);

export const PluginUIProvider = ({ pluginKey, plugin: pluginProp, children }) => {
  const storePlugin = usePluginsStore(
    useCallback((state) => (pluginKey ? state.plugins[pluginKey] : null), [pluginKey])
  );

  const plugin = storePlugin || pluginProp || { key: pluginKey };

  const sourceCacheRef = useRef(new Map());
  const subscribersRef = useRef(new Map());
  const inFlightRef = useRef(new Map());
  const refCountRef = useRef(new Map());

  const saveSettings = useCallback(
    async (settings) => {
      if (!pluginKey) return {};
      const updated = await API.updatePluginSettings(pluginKey, settings);
      return updated;
    },
    [pluginKey]
  );

  const runAction = useCallback(
    async (actionId, params = {}, options = {}) => {
      if (!pluginKey) return null;
      return API.runPluginAction(pluginKey, actionId, params, options);
    },
    [pluginKey]
  );

  const resolveResource = useCallback(
    async (resourceId, params = {}, options = {}) => {
      if (!pluginKey) return null;
      return API.resolvePluginResource(pluginKey, resourceId, params, options);
    },
    [pluginKey]
  );

  const getSourceSnapshot = useCallback((id) => sourceCacheRef.current.get(id), []);

  const setSourceSnapshot = useCallback((id, snapshot) => {
    if (!id) return;
    sourceCacheRef.current.set(id, snapshot);
    const subs = subscribersRef.current.get(id);
    if (subs) {
      subs.forEach((listener) => {
        try {
          listener(snapshot);
        } catch (err) {
          console.warn('Plugin data source listener error', err);
        }
      });
    }
  }, []);

  const subscribeSource = useCallback((id, listener) => {
    if (!id || typeof listener !== 'function') {
      return () => {};
    }
    const subs = subscribersRef.current.get(id) || new Set();
    subs.add(listener);
    subscribersRef.current.set(id, subs);
    return () => {
      const current = subscribersRef.current.get(id);
      if (!current) return;
      current.delete(listener);
      if (current.size === 0) {
        subscribersRef.current.delete(id);
      }
    };
  }, []);

  const runSourceFetch = useCallback((id, factory) => {
    if (!id || typeof factory !== 'function') {
      return Promise.resolve(null);
    }
    const existing = inFlightRef.current.get(id);
    if (existing) {
      return existing;
    }
    const promise = (async () => {
      try {
        return await factory();
      } finally {
        inFlightRef.current.delete(id);
      }
    })();
    inFlightRef.current.set(id, promise);
    return promise;
  }, []);

  const acquireSourceOwner = useCallback((id) => {
    if (!id) return 0;
    const next = (refCountRef.current.get(id) || 0) + 1;
    refCountRef.current.set(id, next);
    return next;
  }, []);

  const releaseSourceOwner = useCallback((id) => {
    if (!id) return 0;
    const current = refCountRef.current.get(id) || 0;
    const next = Math.max(current - 1, 0);
    if (next === 0) {
      refCountRef.current.delete(id);
    } else {
      refCountRef.current.set(id, next);
    }
    return next;
  }, []);

  const value = useMemo(
    () => ({
      pluginKey,
      plugin,
      schema: plugin?.ui_schema || {},
      settings: plugin?.settings || {},
      saveSettings,
      runAction,
      resolveResource,
      getSourceSnapshot,
      setSourceSnapshot,
      subscribeSource,
      runSourceFetch,
      acquireSourceOwner,
      releaseSourceOwner,
    }),
    [
      pluginKey,
      plugin,
      saveSettings,
      runAction,
      resolveResource,
      getSourceSnapshot,
      setSourceSnapshot,
      subscribeSource,
      runSourceFetch,
      acquireSourceOwner,
      releaseSourceOwner,
    ]
  );

  return <PluginUIContext.Provider value={value}>{children}</PluginUIContext.Provider>;
};

export const usePluginUI = () => {
  const ctx = useContext(PluginUIContext);
  if (!ctx) {
    throw new Error('usePluginUI must be used within a PluginUIProvider');
  }
  return ctx;
};

export default PluginUIContext;
