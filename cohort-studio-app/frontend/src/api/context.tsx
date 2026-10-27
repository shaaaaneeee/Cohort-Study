import { createContext, useContext, type ReactNode } from "react";

import { api as defaultClient, type ApiClient } from "./client";

const ApiContext = createContext<ApiClient>(defaultClient);

/** Components get the API client from here, so tests can hand them a fake one. */
export function ApiProvider({ client, children }: { client: ApiClient; children: ReactNode }) {
  return <ApiContext.Provider value={client}>{children}</ApiContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useApi(): ApiClient {
  return useContext(ApiContext);
}
