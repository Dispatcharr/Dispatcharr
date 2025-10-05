export const getByPath = (source, path, fallback = undefined) => {
  if (!path || typeof path !== 'string') {
    return fallback;
  }
  const segments = path.split('.');
  let current = source;
  for (const segment of segments) {
    if (current == null) {
      return fallback;
    }
    const match = segment.match(/^(\w+)(\[(\d+)])?$/);
    if (!match) {
      return fallback;
    }
    const key = match[1];
    current = current[key];
    if (match[3] !== undefined && Array.isArray(current)) {
      const index = Number(match[3]);
      current = current[index];
    }
  }
  return current ?? fallback;
};

export const applyTemplate = (value, context = {}) => {
  if (typeof value === 'string') {
    return value.replace(/\{\{\s*([^}]+)\s*}}/g, (_, expr) => {
      const trimmed = expr.trim();
      const resolved = getByPath(context, trimmed, '');
      return resolved == null ? '' : String(resolved);
    });
  }

  if (Array.isArray(value)) {
    return value.map((item) => applyTemplate(item, context));
  }

  if (value && typeof value === 'object') {
    const next = {};
    for (const key of Object.keys(value)) {
      next[key] = applyTemplate(value[key], context);
    }
    return next;
  }

  return value;
};

export const ensureArray = (input) => {
  if (Array.isArray(input)) {
    return input;
  }
  if (input === null || input === undefined) {
    return [];
  }
  return [input];
};

export const safeEntries = (input) => {
  if (!input || typeof input !== 'object') {
    return [];
  }
  const pairs = [];
  for (const key in input) {
    if (Object.prototype.hasOwnProperty.call(input, key)) {
      pairs.push([key, input[key]]);
    }
  }
  return pairs;
};

export const toNumber = (value, fallback = 0) => {
  if (typeof value === 'number') return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const num = Number(value);
    return Number.isNaN(num) ? fallback : num;
  }
  return fallback;
};

export const deepMerge = (target = {}, source = {}) => {
  const safeTarget = target && typeof target === 'object' && !Array.isArray(target) ? target : {};
  const safeSource = source && typeof source === 'object' && !Array.isArray(source) ? source : {};
  const output = { ...safeTarget };
  for (const [key, value] of safeEntries(safeSource)) {
    if (
      value &&
      typeof value === 'object' &&
      !Array.isArray(value) &&
      typeof output[key] === 'object' &&
      !Array.isArray(output[key])
    ) {
      output[key] = deepMerge(output[key], value);
    } else {
      output[key] = value;
    }
  }
  return output;
};

export const pickFields = (obj, fields = []) => {
  if (!obj || typeof obj !== 'object') {
    return {};
  }
  if (!fields || fields.length === 0) {
    return { ...obj };
  }
  return fields.reduce((acc, field) => {
    if (Object.prototype.hasOwnProperty.call(obj, field)) {
      acc[field] = obj[field];
    }
    return acc;
  }, {});
};

export const boolFrom = (value, fallback = false) => {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'string') {
    return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase());
  }
  if (typeof value === 'number') {
    return value !== 0;
  }
  return fallback;
};

export const clamp = (value, min, max) => {
  const num = toNumber(value, min);
  if (typeof min === 'number' && num < min) return min;
  if (typeof max === 'number' && num > max) return max;
  return num;
};

export const uniqueId = (() => {
  let counter = 0;
  return (prefix = 'id') => {
    counter += 1;
    return `${prefix}-${counter}`;
  };
})();
