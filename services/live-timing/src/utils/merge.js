/**
 * @file merge.js
 * @description Utility for deeply merging F1 SignalR Core delta payloads into an existing state tree.
 * F1 SignalR uses a delta protocol where only changed fields in channels like TimingData or TimingAppData
 * are sent in each message. Deep merging ensures that nested structures (such as Sectors, Speeds, or Stints)
 * are cleanly updated without overwriting existing sibling fields.
 */

/**
 * Checks if a value is a plain object (and not null, array, Date, etc.).
 * @param {any} item - Value to check.
 * @returns {boolean} True if the value is a plain object.
 */
function isPlainObject(item) {
    return item !== null && typeof item === 'object' && !Array.isArray(item) && !(item instanceof Date);
}

/**
 * [Race Center addition] Checks if an object is indexed by position.
 *
 * The F1 feed sends the same collection in two shapes: the initial snapshot
 * sends arrays (`Stints: [{...}]`) and the deltas send objects keyed by
 * position (`Stints: {"1": {...}}`). They are the same collection.
 *
 * @param {any} item - Value to check.
 * @returns {boolean} True if the object only has numeric keys.
 */
function isIndexedObject(item) {
    if (!isPlainObject(item)) return false;
    const keys = Object.keys(item);
    if (!keys.length) return false;
    return keys.every((key) => /^\d+$/.test(key));
}

/**
 * [Race Center addition] Converts an indexed object into an array.
 *
 * @param {Object} item - Object with numeric keys.
 * @returns {Array} The values, ordered by position.
 */
function indexedToArray(item) {
    return Object.keys(item)
        .sort((a, b) => Number(a) - Number(b))
        .map((key) => item[key]);
}

/**
 * [Race Center addition] Converts an array into an object indexed by position.
 *
 * @param {Array} item - Array of values.
 * @returns {Object} The values, keyed by position.
 */
function arrayToIndexed(item) {
    const result = {};
    item.forEach((value, index) => {
        result[index] = value;
    });
    return result;
}

/**
 * [Race Center addition] Converts any collection shape into an indexed object.
 *
 * An array keeps its positions; an indexed object keeps its own keys (so a
 * stint added on position 1 does not end up on position 0).
 *
 * @param {Array|Object} valor - Collection in either shape.
 * @returns {Object} The values, keyed by position.
 */
function aIndexed(valor) {
    if (Array.isArray(valor)) return arrayToIndexed(valor);
    if (isIndexedObject(valor)) return Object.assign({}, valor);
    return arrayToIndexed(indexedToArray(valor));
}

/**
 * Deeply merges a source object (SignalR delta) into a target object (in-memory state).
 * Modifies target directly and returns it. Does not modify key names or cases.
 *
 * @param {Object} target - The destination state object.
 * @param {Object} source - The delta object to merge into target.
 * @returns {Object} The merged target object.
 */
function deepMerge(target, source) {
    if (!isPlainObject(target) || !isPlainObject(source)) {
        return source !== undefined ? source : target;
    }

    for (const key of Object.keys(source)) {
        const sourceVal = source[key];

        if (sourceVal !== undefined) {
            if (isPlainObject(sourceVal) || Array.isArray(sourceVal)) {
                // [Race Center addition] When the target and the source hold the
                // same collection in different shapes (array in the snapshot,
                // indexed object in the deltas), they are merged instead of
                // replacing each other. Replacing was the bug that emptied the
                // tyre column in the middle of a race: a delta with a single
                // stint replaced the whole list, and with it the compound of
                // the previous stint.
                const targetVal = target[key];
                const shapeDistinta =
                    (Array.isArray(sourceVal) && isIndexedObject(targetVal)) ||
                    (isPlainObject(sourceVal) && Array.isArray(targetVal));

                if (shapeDistinta) {
                    const indexedTarget = aIndexed(targetVal);
                    const indexedSource = aIndexed(sourceVal);
                    const merged = deepMerge(indexedTarget, indexedSource);
                    target[key] = Array.isArray(targetVal) ? indexedToArray(merged) : merged;
                    continue;
                }

                if (isPlainObject(sourceVal)) {
                    if (!isPlainObject(target[key])) {
                        target[key] = {};
                    }
                    deepMerge(target[key], sourceVal);
                } else if (Array.isArray(sourceVal)) {
                    // For arrays in SignalR payloads (e.g., RaceControlMessages or specific arrays),
                    // we perform a slice copy to replace the array cleanly.
                    target[key] = sourceVal.slice();
                } else {
                    target[key] = sourceVal;
                }
            } else {
                target[key] = sourceVal;
            }
        }
    }

    return target;
}

module.exports = {
    deepMerge,
    isPlainObject,
    isIndexedObject,
    indexedToArray,
    arrayToIndexed
};
