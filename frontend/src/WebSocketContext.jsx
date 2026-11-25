import { createContext, useContext } from 'react';

export const WebsocketContext = createContext([false, () => {}, null]);

export const useWebSocket = () => useContext(WebsocketContext);
