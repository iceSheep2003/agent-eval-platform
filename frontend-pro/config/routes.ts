export default [
  { path: '/user/login', layout: false, component: './user/login' },
  { path: '/', redirect: '/overview' },
  {
    path: '/overview',
    name: '评测总览',
    icon: 'DashboardOutlined',
    component: './overview',
  },
  {
    path: '/agents',
    name: 'Agent 管理',
    icon: 'RobotOutlined',
    component: './agents',
  },
  { path: '/agents/:id', component: './agent-detail', hideInMenu: true },
  {
    path: '/skills',
    name: 'Skill 管理',
    icon: 'BranchesOutlined',
    component: './evolution/skills',
  },
  {
    path: '/mcp',
    name: 'MCP 管理',
    icon: 'ApiOutlined',
    component: './evolution/mcp',
  },
  {
    path: '/knowledge',
    name: '知识库管理',
    icon: 'DatabaseOutlined',
    component: './evolution/knowledge',
  },
  {
    path: '/evaluation',
    name: '评测中心',
    icon: 'ExperimentOutlined',
    routes: [
      { path: '/evaluation', redirect: '/evaluation/runs' },
      { path: '/evaluation/runs', name: '实验运行', component: './runs' },
      { path: '/evaluation/datasets', name: '数据集', component: './datasets' },
      {
        path: '/evaluation/capabilities',
        name: '评测策略',
        component: './capabilities',
      },
    ],
  },
  { path: '/*', layout: false, component: './exception/404' },
];
