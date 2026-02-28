/**
 * Rate limiter for controlling concurrent promise execution
 */
class Limiter {
  /**
   * Execute promises with a concurrency limit
   * @param n - Maximum number of concurrent promises
   * @param list - Array of functions that return promises
   * @returns Promise that resolves when all promises complete
   */
  static all<T>(n: number, list: Array<() => Promise<T>>): Promise<T[]> {
    if (!list || !list.length) {
      return Promise.resolve([]);
    }

    const tail = list.splice(n);
    const head = list;
    const resolved: Promise<T>[] = [];
    let processed = 0;

    return new Promise((resolve) => {
      head.forEach((fn) => {
        const promise = fn();
        resolved.push(promise);
        promise.then((result) => {
          runNext();
          return result;
        });
      });

      function runNext() {
        if (processed === tail.length) {
          resolve(Promise.all(resolved));
        } else {
          resolved.push(
            tail[processed]().then((result) => {
              runNext();
              return result;
            })
          );
          processed++;
        }
      }
    });
  }
}

export default Limiter;
