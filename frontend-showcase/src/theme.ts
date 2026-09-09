import type { ThemeConfig } from 'antd';

/** 与控制台 `frontend-pro` 保持同一套品牌 token，两个产品看起来是一家的。 */
export const theme: ThemeConfig = {
  token: {
    colorPrimary: '#4f7cff',
    colorInfo: '#4f7cff',
    colorBgLayout: '#f6f8fc',
    colorBgContainer: '#ffffff',
    colorBorder: '#e6ebf2',
    colorBorderSecondary: '#edf1f6',
    colorText: '#172033',
    colorTextSecondary: '#64748b',
    borderRadius: 10,
    borderRadiusLG: 14,
    fontFamily: 'Inter, "PingFang SC", "Microsoft YaHei", sans-serif',
  },
};

/** 通道配色：TEST 中性、LIVESH 警示、LIVE 肯定。 */
export const CHANNEL_COLOR: Record<string, string> = {
  test: '#64748b',
  liversh: '#d48806',
  live: '#15803d',
};
