import React, {
  useState,
  useEffect,
  useRef,
  createContext,
  useContext,
} from 'react';
import useStreamsStore from './store/streams';
import { notifications } from '@mantine/notifications';
import useChannelsStore from './store/channels';
import usePlaylistsStore from './store/playlists';

export const WebsocketContext = createContext(false, null, () => {});

export const WebsocketProvider = ({ children }) => {
  const [isReady, setIsReady] = useState(false);
  const [val, setVal] = useState(null);

  const { fetchStreams } = useStreamsStore();
  const { setChannelStats, fetchChannelGroups } = useChannelsStore();
  const { setRefreshProgress } = usePlaylistsStore();

  const ws = useRef(null);

  useEffect(() => {
    let wsUrl = `${window.location.host}/ws/`;
    if (import.meta.env.DEV) {
      wsUrl = `${window.location.hostname}:8001/ws/`;
    }

    if (window.location.protocol.match(/https/)) {
      wsUrl = `wss://${wsUrl}`;
    } else {
      wsUrl = `ws://${wsUrl}`;
    }

    const socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      console.log('websocket connected');
      setIsReady(true);
    };

    // Reconnection logic
    socket.onclose = () => {
      setIsReady(false);
      setTimeout(() => {
        const reconnectWs = new WebSocket(wsUrl);
        reconnectWs.onopen = () => setIsReady(true);
      }, 3000); // Attempt to reconnect every 3 seconds
    };

    socket.onmessage = async (event) => {
      event = JSON.parse(event.data);
      switch (event.data.type) {
        case 'm3u_refresh':
          console.log('inside m3u_refresh event');
          if (event.data.success) {
            fetchStreams();
            notifications.show({
              message: event.data.message,
              color: 'green.5',
            });
          } else if (event.data.progress) {
            if (event.data.progress == 100) {
              fetchStreams();
              fetchChannelGroups();
            }
            setRefreshProgress(event.data.account, event.data.progress);
          }
          break;

        case 'channel_stats':
          setChannelStats(JSON.parse(event.data.stats));
          break;

        default:
          console.error(`Unknown websocket event type: ${event.type}`);
          break;
      }
    };

    ws.current = socket;

    return () => {
      socket.close();
    };
  }, []);

  const ret = [isReady, val, ws.current?.send.bind(ws.current)];

  return (
    <WebsocketContext.Provider value={ret}>
      {children}
    </WebsocketContext.Provider>
  );
};

export const useWebSocket = () => {
  const socket = useContext(WebsocketContext);
  return socket;
};
