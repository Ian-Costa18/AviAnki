// A bounded, in-order prefetcher: turns "fetch one file" into the media feed `buildDeck` wants
// (see the header of ../deck.js). Downloads run `concurrency` at a time, results are yielded in
// the order of `items`, and the next download starts only when a result has been handed over,
// so at most `concurrency` buffers exist beyond the one the writer is holding.

/**
 * @param {string[]} items  what to fetch, in the order the writer needs it
 * @param {(item: string, signal: AbortSignal) => Promise<Uint8Array>} fetchOne
 * @param {{concurrency?: number}} [options]  6 by default (the browser's per-host connection limit)
 * @returns {AsyncGenerator<{name: string, data: Uint8Array}>}
 */
export async function* orderedPrefetch(items, fetchOne, { concurrency = 6 } = {}) {
  if (!(concurrency >= 1)) throw new RangeError("concurrency must be at least 1");
  const controller = new AbortController();
  const pending = []; // promises for items[next - pending.length .. next)
  let next = 0;
  const start = () => {
    const promise = Promise.resolve(fetchOne(items[next], controller.signal));
    promise.catch(() => {}); // a failure is reported when its turn comes, not as "unhandled"
    pending.push(promise);
    next++;
  };
  try {
    while (next < items.length && pending.length < concurrency) start();
    for (let i = 0; i < items.length; i++) {
      const data = await pending.shift();
      if (next < items.length) start();
      yield { name: items[i], data };
    }
  } finally {
    controller.abort(); // on an error or an early exit, cancel what is still in flight
  }
}
