"use client";

import { createContext, useContext } from "react";

export interface SearchCtx {
  search: string;
  setSearch: (v: string) => void;
  suggestions: string[];
  setSuggestions: (v: string[]) => void;
}

export const SearchContext = createContext<SearchCtx>({
  search: "",
  setSearch: () => {},
  suggestions: [],
  setSuggestions: () => {},
});

export function useTpaSearch() {
  return useContext(SearchContext);
}
