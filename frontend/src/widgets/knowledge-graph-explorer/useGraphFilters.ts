import { useState } from "react";

export interface GraphFilters {
  searchQuery: string;
  documentFilter: string;
  minWeight: number;
  hopDepth: number;
}

export function useGraphFilters() {
  const [searchQuery, setSearchQuery] = useState("");
  const [documentFilter, setDocumentFilter] = useState("all");
  const [minWeight, setMinWeight] = useState(0);
  const [hopDepth, setHopDepth] = useState(0);

  return {
    searchQuery,
    setSearchQuery,
    documentFilter,
    setDocumentFilter,
    minWeight,
    setMinWeight,
    hopDepth,
    setHopDepth,
  };
}
