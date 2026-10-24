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
        }
    }

    return target;
}

module.exports = {
    deepMerge,
    isPlainObject
};
