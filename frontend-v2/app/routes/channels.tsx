import { useCallback } from "react";
import type { Route } from "./+types/channels";
import { Allotment } from "allotment";
import ChannelsTable from "./channels/ChannelsTable";
import storage from "~/lib/safe-storage";
import { getM3uUrlBase, getEpgUrlBase, getHdhrUrlBase } from "~/lib/urls";

export function meta({}: Route.MetaArgs) {
  return [
    { title: "Channels - Dispatcharr" },
    { name: "description", content: "Manage your channels" },
  ];
}

export async function loader({ request }: Route.LoaderArgs) {
  // Extract base URLs from the request (works server-side AND client-side)
  return {
    m3uUrlBase: getM3uUrlBase(request),
    epgUrlBase: getEpgUrlBase(request),
    hdhrUrlBase: getHdhrUrlBase(request),
  };
}

export default function Channels({ loaderData }: Route.ComponentProps) {
  const defaultSizes = storage.getJSON<number[]>("channels-splitter-sizes") || [
    50, 50,
  ];

  const handleSplitChange = useCallback((sizes: number[]) => {
    storage.setJSON("channels-splitter-sizes", sizes);
  }, []);

  return (
    <div className="flex h-full w-full">
      <Allotment
        defaultSizes={defaultSizes}
        onChange={handleSplitChange}
        className="h-full w-full"
      >
        <Allotment.Pane minSize={300}>
          <div className="flex h-full flex-col p-2">
            <ChannelsTable
              m3uUrlBase={loaderData.m3uUrlBase}
              epgUrlBase={loaderData.epgUrlBase}
              hdhrUrlBase={loaderData.hdhrUrlBase}
            />
          </div>
        </Allotment.Pane>
        <Allotment.Pane minSize={300}>
          <div className="flex h-full flex-col p-2">
            <ChannelsTable
              m3uUrlBase={loaderData.m3uUrlBase}
              epgUrlBase={loaderData.epgUrlBase}
              hdhrUrlBase={loaderData.hdhrUrlBase}
            />
          </div>
        </Allotment.Pane>
      </Allotment>
    </div>
  );
}
