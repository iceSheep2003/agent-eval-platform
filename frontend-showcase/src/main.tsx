import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { SessionProvider } from './session';
import { theme } from './theme';
// Markdown 渲染用组件自带的样式与主题，不手写排版
import '@ant-design/x-markdown/es/XMarkdown/index.css';
import '@ant-design/x-markdown/themes/light.css';
import './styles.css';

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <ConfigProvider locale={zhCN} theme={theme}>
      <AntApp>
        <BrowserRouter>
          <SessionProvider>
            <App />
          </SessionProvider>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  </StrictMode>,
);
