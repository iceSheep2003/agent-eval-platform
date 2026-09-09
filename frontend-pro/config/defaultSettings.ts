import type { ProLayoutProps } from '@ant-design/pro-components';

/**
 * @name
 */
const Settings: ProLayoutProps & {
  logo?: string;
} = {
  navTheme: 'light',
  colorPrimary: '#4f7cff',
  layout: 'mix',
  contentWidth: 'Fluid',
  fixedHeader: true,
  fixSiderbar: true,
  colorWeak: false,
  title: 'Eval Loom',
  logo: '/logo.svg',
  iconfontUrl: '',
  token: {
    sider: {
      colorMenuBackground: '#ffffff',
      colorTextMenu: '#64748b',
      colorTextMenuSelected: '#315fd6',
      colorBgMenuItemSelected: '#eef4ff',
    },
    header: {
      colorBgHeader: 'rgba(255, 255, 255, 0.92)',
      colorHeaderTitle: '#172033',
    },
  },
};

export default Settings;
