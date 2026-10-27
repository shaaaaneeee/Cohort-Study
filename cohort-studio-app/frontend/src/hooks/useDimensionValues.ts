// The values of one dimension, fetched once per page load. A failed request
// is forgotten so the next attempt tries again.
import { useEffect, useState } from "react";

import type { ApiClient } from "../api/client";

const cache = new Map<string, Promise<string[]>>();

export function valuesOf(client: ApiClient, source: string, dimension: string): Promise<string[]> {
  const key = `${source}/${dimension}`;
  let request = cache.get(key);
  if (!request) {
    request = client.values(source, dimension).catch((error: unknown) => {
      cache.delete(key);
      throw error;
    });
    cache.set(key, request);
  }
  return request;
}

export function clearValuesCache(): void {
  cache.clear();
}

export interface DimensionValues {
  values: string[];
  loading: boolean;
  error: string | null;
}

export function useDimensionValues(
  client: ApiClient,
  source: string,
  dimension: string,
): DimensionValues {
  const key = `${source}/${dimension}`;
  const [state, setState] = useState<{ key: string; values: string[]; error: string | null }>({
    key: "",
    values: [],
    error: null,
  });
  useEffect(() => {
    let live = true;
    valuesOf(client, source, dimension).then(
      (values) => {
        if (live) setState({ key, values, error: null });
      },
      (error: unknown) => {
        if (live) {
          const message = error instanceof Error ? error.message : String(error);
          setState({ key, values: [], error: message });
        }
      },
    );
    return () => {
      live = false;
    };
  }, [client, source, dimension, key]);
  // Until this dimension's answer arrives, show it as loading.
  if (state.key !== key) return { values: [], loading: true, error: null };
  return { values: state.values, loading: false, error: state.error };
}
