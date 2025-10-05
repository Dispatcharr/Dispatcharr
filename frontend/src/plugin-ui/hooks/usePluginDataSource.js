import { useEffect, useMemo, useState, useCallback, useRef } from 'react';
import { notifications } from '@mantine/notifications';
import { usePluginUI } from '../PluginContext';
import { useWebSocket } from '../../WebSocket';
import {
  applyTemplate,
  deepMerge,
  ensureArray,
  getByPath,
  boolFrom,
} from '../utils';

const DEFAULT_DATA = null;

const resolveConfig = (schemaSources = {}, source, override = {}) => {
  const base =
    typeof source === 'string' ? schemaSources[source] || { id: source } : source || {};
  return deepMerge(base, override);
};

const extractData = (payload, config) => {
  if (!config) return payload;
  let result = payload;
  const extractPath = config.extract || config.responsePath || config.path;
  if (extractPath) {
    const extracted = getByPath(result, extractPath);
    if (extracted !== undefined) {
      result = extracted;
    }
  }
  if (config.pick && Array.isArray(result)) {
    result = result.map((item) => {
      const picked = {};
      config.pick.forEach((field) => {
        if (item && Object.prototype.hasOwnProperty.call(item, field)) {
          picked[field] = item[field];
        }
      });
      return picked;
    });
  }
  if (config.default !== undefined && (result === undefined || result === null)) {
    return config.default;
  }
  return result;
};

const matchesFilter = (eventData, filter = {}) => {
  if (!filter || typeof filter !== 'object') {
    return true;
  }
  for (const key in filter) {
    if (!Object.prototype.hasOwnProperty.call(filter, key)) continue;
    const expected = filter[key];
    const actual = getByPath(eventData, key, getByPath(eventData?.payload, key));
    if (Array.isArray(expected)) {
      if (!expected.includes(actual)) {
        return false;
      }
    } else if (actual !== expected) {
      return false;
    }
  }
  return true;
};

const normalizeMode = (mode) => {
  if (!mode) return 'refresh';
  return String(mode).toLowerCase();
};

const ensurePlugin = (pluginKey) => {
  if (!pluginKey) {
    throw new Error('Plugin key is required for data sources');
  }
};

const useStableCallback = (fn) => {
  const ref = useRef(fn);
  useEffect(() => {
    ref.current = fn;
  }, [fn]);
  return useCallback((...args) => ref.current?.(...args), []);
};

const useLatest = (value) => {
  const ref = useRef(value);
  useEffect(() => {
    ref.current = value;
  }, [value]);
  return ref;
};

const createErrorNotification = (title, message) => {
  notifications.show({
    title,
    message,
    color: 'red',
  });
};

const defaultSubscribeFilter = (pluginKey) => ({
  plugin: pluginKey,
});

const buildFinalParams = (configParams = {}, stateParams = {}, runtimeParams = {}) => {
  return {
    ...(configParams || {}),
    ...(stateParams || {}),
    ...(runtimeParams || {}),
  };
};

const resolveTemplate = (input, context) => {
  if (!input) return input;
  return applyTemplate(input, context);
};

const resolveDataValue = (value, current) => {
  if (typeof value === 'function') {
    try {
      return value(current ?? {});
    } catch (error) {
      if (import.meta?.env?.DEV) {
        // eslint-disable-next-line no-console
        console.warn('[Dispatcharr Plugin UI] Data factory threw', error);
      }
      return current ?? {};
    }
  }
  return value;
};

const usePluginDataSource = (source, options = {}) => {
  const {
    pluginKey,
    schema,
    runAction,
    resolveResource,
    getSourceSnapshot,
    setSourceSnapshot,
    subscribeSource,
    runSourceFetch,
    acquireSourceOwner,
    releaseSourceOwner,
  } = usePluginUI();
  ensurePlugin(pluginKey);
  const schemaSources = schema?.dataSources || {};

  const config = useMemo(
    () => resolveConfig(schemaSources, source, options.override || {}),
    [schemaSources, source, options.override]
  );

  const sourceId = config.id || config.key || (typeof source === 'string' ? source : config.action || config.resource);
  const type = config.type || (config.resource ? 'resource' : 'action');

  const baseParams = useMemo(
    () => buildFinalParams(config.params, options.params),
    [config.params, options.params]
  );

  const cachedSnapshot = useMemo(() => getSourceSnapshot(sourceId), [getSourceSnapshot, sourceId]);

  const initialData = useMemo(() => {
    try {
      if (cachedSnapshot && Object.prototype.hasOwnProperty.call(cachedSnapshot, 'data')) {
        return resolveDataValue(cachedSnapshot.data, undefined);
      }
      if (config.default !== undefined) {
        return resolveDataValue(extractData(config.default, config), undefined);
      }
      return DEFAULT_DATA;
    } catch (error) {
      // eslint-disable-next-line no-console
      console.error('[Dispatcharr Plugin UI] Failed to derive initial data', {
        source,
        override: options.override,
        cachedSnapshot,
        config,
      }, error);
      throw error;
    }
  }, [cachedSnapshot, config, source, options.override]);

  const initialError = cachedSnapshot?.error ?? null;
  const initialLastUpdated = cachedSnapshot?.lastUpdated ?? null;
  const initialStatus = cachedSnapshot?.status ?? {};

  const normaliseInitialState = useCallback((value) => {
    if (value === null || value === undefined) {
      return [];
    }
    if (Array.isArray(value)) {
      return [...value];
    }
    if (typeof value === 'object') {
      const safeObject = value ?? {};
      return { ...safeObject };
    }
    return value;
  }, []);

  const [data, setDataState] = useState(() => normaliseInitialState(initialData));
  const dataRef = useLatest(data);
  const setData = useCallback(
    (next) => {
      try {
        const rawValue = typeof next === 'function' ? next(dataRef.current ?? {}) : next;
        const value = resolveDataValue(rawValue, dataRef.current);
        setDataState(normaliseInitialState(value));
      } catch (error) {
        // eslint-disable-next-line no-console
        console.error('[Dispatcharr Plugin UI] Failed to update data state', { next }, error);
        throw error;
      }
    },
    [normaliseInitialState, dataRef]
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(initialError);
  const [lastUpdated, setLastUpdated] = useState(initialLastUpdated);
  const [status, setStatus] = useState(initialStatus);

  const paramsRef = useLatest(baseParams);
  const ownerRef = useRef(false);
  const [isOwner, setIsOwner] = useState(false);

  const [, , socketExtras] = useWebSocket();
  const wsSubscribe = socketExtras?.subscribe;

  const fetchData = useCallback(
    async (runtimeParams = {}, meta = {}) => {
      if (!sourceId) {
        return null;
      }
      const isController = ownerRef.current || meta.force;
      if (!isController) {
        const snapshotData = getSourceSnapshot(sourceId)?.data;
        return resolveDataValue(snapshotData, dataRef.current);
      }
      setLoading(true);
      setError(null);
      try {
        const snapshot = await runSourceFetch(sourceId, async () => {
          const finalParams = buildFinalParams(
            config.params,
            paramsRef.current,
            runtimeParams
          );
          const templatedParams = resolveTemplate(finalParams, meta.context || {});
          let response = null;
          if (type === 'resource') {
            response = await resolveResource(
              config.resource || sourceId,
              templatedParams,
              {
                allowDisabled: boolFrom(
                  meta.allowDisabled ?? config.allowDisabled ?? options.allowDisabled,
                  false
                ),
              }
            );
          } else if (type === 'static') {
            response = config.data ?? config.value ?? null;
          } else if (type === 'url' && config.url) {
            const url = resolveTemplate(config.url, templatedParams);
            const method = (config.method || 'GET').toUpperCase();
            const fetchOptions = {
              method,
            };
            if (method !== 'GET') {
              fetchOptions.body = JSON.stringify(templatedParams || {});
              fetchOptions.headers = {
                'Content-Type': 'application/json',
              };
            }
            const res = await fetch(url, fetchOptions);
            response = await res.json();
          } else {
            response = await runAction(
              config.action || sourceId,
              templatedParams,
              config.requestOptions || {}
            );
          }

          const payload = response?.result ?? response;
          const transformed = resolveDataValue(extractData(payload, config), dataRef.current);
          const nextSnapshot = {
            data: transformed,
            status: {
              ok: true,
              meta: {
                sourceId,
                params: templatedParams,
              },
            },
            lastUpdated: new Date(),
            error: null,
          };
          setSourceSnapshot(sourceId, nextSnapshot);
          if (options.onData) {
            options.onData(transformed);
          }
          return nextSnapshot;
        });

        if (snapshot) {
          setData(snapshot.data);
          setStatus(snapshot.status || {});
          setLastUpdated(snapshot.lastUpdated || new Date());
        }
        return snapshot?.data ?? null;
      } catch (err) {
        const failureSnapshot = {
          data: dataRef.current,
          status: { ok: false },
          lastUpdated: new Date(),
          error: err,
        };
        setSourceSnapshot(sourceId, failureSnapshot);
        setError(err);
        setStatus({ ok: false, error: err });
        if (options.notifyOnError || config.notifyOnError) {
          createErrorNotification(
            options.errorTitle || config.errorTitle || 'Plugin data source failed',
            err?.message || String(err)
          );
        }
        return null;
      } finally {
        setLoading(false);
      }
    },
    [
      config,
      paramsRef,
      resolveResource,
      runAction,
      sourceId,
      type,
      options.allowDisabled,
      options.notifyOnError,
      options.errorTitle,
      options.onData,
      runSourceFetch,
      setSourceSnapshot,
      dataRef,
      getSourceSnapshot,
    ]
  );

  const refresh = useStableCallback((runtimeParams = {}, meta = {}) =>
    fetchData(runtimeParams, { ...meta, force: true })
  );

  // Auto load
  useEffect(() => {
    if (options.lazy || config.lazy || !isOwner) {
      return undefined;
    }
    let cancelled = false;
    (async () => {
      const result = await fetchData({}, { force: true });
      if (!cancelled && options.onLoad) {
        options.onLoad(result);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchData, options.lazy, options.onLoad, config.lazy, isOwner]);

  // Interval refresh
  useEffect(() => {
    const interval = config.refresh?.interval ?? options.refreshInterval;
    if (!isOwner || !interval || interval <= 0) return undefined;
    const timer = setInterval(() => {
      fetchData({}, { force: true });
    }, interval * 1000);
    return () => clearInterval(timer);
  }, [config.refresh?.interval, options.refreshInterval, fetchData, isOwner]);

  // Subscribe to websocket events
  useEffect(() => {
    if (!wsSubscribe || !config.subscribe) {
      return undefined;
    }
    const spec = typeof config.subscribe === 'string'
      ? { event: config.subscribe }
      : config.subscribe;
    const mode = normalizeMode(spec.mode);
    const filter = {
      ...defaultSubscribeFilter(pluginKey),
      ...(spec.filter || {}),
    };
    const limit = spec.limit || config.limit;

    const handler = (event) => {
      const eventData = event?.data;
      if (!eventData) return;
    if (spec.event && eventData.type !== spec.event) return;
    if (spec.channel && eventData.channel !== spec.channel) return;
    if (
      spec.plugin &&
      eventData.plugin !== (spec.plugin === 'self' ? pluginKey : spec.plugin)
    )
      return;
      if (filter && !matchesFilter(eventData, filter)) return;

      if (mode === 'append') {
        const payloadPath = spec.path || 'payload';
        const payload = getByPath(eventData, payloadPath, eventData.payload ?? eventData);
        if (payload !== undefined) {
          const next = [...ensureArray(dataRef.current || [])];
          const chunk = ensureArray(payload);
          const merged = spec.prepend ? [...chunk, ...next] : [...next, ...chunk];
          const bounded = limit ? merged.slice(-limit) : merged;
          setData(resolveDataValue(bounded, dataRef.current));
          setLastUpdated(new Date());
        }
      } else if (mode === 'patch') {
        const patchPath = spec.path || 'payload';
        const patch = getByPath(eventData, patchPath, eventData.payload ?? {});
        if (patch && typeof patch === 'object') {
          const base = dataRef.current;
          const safeBase =
            base && typeof base === 'object' && !Array.isArray(base) ? base : {};
          setData({ ...safeBase, ...patch });
          setLastUpdated(new Date());
        }
      } else if (ownerRef.current) {
        fetchData({}, { force: true });
      }
    };

    const unsubscribe = wsSubscribe(handler);
    return () => unsubscribe && unsubscribe();
  }, [wsSubscribe, config.subscribe, fetchData, pluginKey, config.limit, dataRef]);

  useEffect(() => {
    const unsubscribe = subscribeSource(sourceId, (snapshot) => {
      if (!snapshot) return;
      if (snapshot.data !== undefined) {
        setData(resolveDataValue(snapshot.data, dataRef.current));
      }
      if (snapshot.status !== undefined) {
        setStatus(snapshot.status || {});
      }
      if (snapshot.lastUpdated) {
        setLastUpdated(snapshot.lastUpdated);
      }
      if (Object.prototype.hasOwnProperty.call(snapshot, 'error')) {
        setError(snapshot.error);
      }
    });
    const existing = getSourceSnapshot(sourceId);
    if (existing) {
      setData(resolveDataValue(existing.data, dataRef.current));
      setStatus(existing.status || {});
      setLastUpdated(existing.lastUpdated || null);
      setError(existing.error || null);
    }
    return unsubscribe;
  }, [getSourceSnapshot, subscribeSource, sourceId, normaliseInitialState]);

  const setParams = useCallback(
    (updater) => {
      paramsRef.current =
        typeof updater === 'function' ? updater(paramsRef.current || {}) : updater;
      fetchData(paramsRef.current, {
        context: { params: paramsRef.current },
        force: true,
      });
    },
    [fetchData, paramsRef]
  );

  useEffect(() => {
    if (!sourceId) return undefined;
    const count = acquireSourceOwner(sourceId);
    const becameOwner = count === 1;
    ownerRef.current = becameOwner;
    setIsOwner(becameOwner);
    const snapshot = getSourceSnapshot(sourceId);
    if (snapshot && snapshot.data !== undefined) {
      setData(resolveDataValue(snapshot.data, dataRef.current));
      setStatus(snapshot.status || {});
      setLastUpdated(snapshot.lastUpdated || null);
      setError(snapshot.error || null);
    } else if (config.default !== undefined) {
      const defaults = resolveDataValue(extractData(config.default, config), dataRef.current);
      setData(defaults);
      setStatus((snapshot && snapshot.status) || {});
      setLastUpdated((snapshot && snapshot.lastUpdated) || null);
      setError((snapshot && snapshot.error) || null);
    }
    if (becameOwner && !(options.lazy || config.lazy)) {
      fetchData({}, { force: true });
    }
    return () => {
      releaseSourceOwner(sourceId);
      ownerRef.current = false;
      setIsOwner(false);
    };
  }, [
    sourceId,
    acquireSourceOwner,
    releaseSourceOwner,
    getSourceSnapshot,
    options.lazy,
    config.lazy,
    fetchData,
    normaliseInitialState,
  ]);

  return {
    id: sourceId,
    data,
    loading,
    error,
    status,
    refresh,
    setParams,
    params: paramsRef.current,
    lastUpdated,
    config,
  };
};

export default usePluginDataSource;
