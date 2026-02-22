import { NavLink } from 'react-router-dom';
import { Home, FileText, Sliders, BookOpen, Palette, Layers, TrendingUp, Lightbulb, Radar, Shield, ScrollText, HelpCircle, Settings, LogOut, Brain, Activity, BarChart3, Bell, Repeat, Database } from 'lucide-react';
import { useLanguage } from '../../contexts/LanguageContext';
import { useAuth } from '../../auth/AuthContext';
import LanguageSelector from '../LanguageSelector';
import './Sidebar.css';

interface NavItem {
  path: string;
  icon: any;
  labelKey: string;
}

interface NavGroup {
  groupKey: string;
  items: NavItem[];
}

const navGroups: NavGroup[] = [
  {
    groupKey: 'nav.group.flywheel',
    items: [
      { path: '/flywheel', icon: Repeat, labelKey: 'nav.flywheel' },
    ],
  },
  {
    groupKey: 'nav.group.intelligence',
    items: [
      { path: '/brain', icon: Brain, labelKey: 'nav.brain' },
      { path: '/saturation', icon: TrendingUp, labelKey: 'nav.saturation' },
      { path: '/radar', icon: Radar, labelKey: 'nav.radar' },
    ],
  },
  {
    groupKey: 'nav.group.opportunities',
    items: [
      { path: '/opportunities', icon: Lightbulb, labelKey: 'nav.opportunities' },
      { path: '/alerts', icon: Bell, labelKey: 'nav.alerts' },
    ],
  },
  {
    groupKey: 'nav.group.create',
    items: [
      { path: '/creatives', icon: Palette, labelKey: 'nav.creatives' },
      { path: '/content-studio', icon: Layers, labelKey: 'nav.contentStudio' },
    ],
  },
  {
    groupKey: 'nav.group.measure',
    items: [
      { path: '/analytics', icon: BarChart3, labelKey: 'nav.analytics' },
      { path: '/data-room', icon: Database, labelKey: 'nav.dataRoom' },
    ],
  },
  {
    groupKey: 'nav.group.ops',
    items: [
      { path: '/dashboard', icon: Home, labelKey: 'nav.dashboard' },
      { path: '/decisions', icon: FileText, labelKey: 'nav.decisions' },
      { path: '/control-panel', icon: Sliders, labelKey: 'nav.control' },
      { path: '/ops', icon: Activity, labelKey: 'nav.ops' },
    ],
  },
  {
    groupKey: 'nav.group.settings',
    items: [
      { path: '/brand-profile', icon: BookOpen, labelKey: 'nav.brandProfile' },
      { path: '/settings', icon: Settings, labelKey: 'nav.settings' },
      { path: '/policies', icon: Shield, labelKey: 'nav.policies' },
      { path: '/audit', icon: ScrollText, labelKey: 'nav.audit' },
      { path: '/help', icon: HelpCircle, labelKey: 'nav.help' },
    ],
  },
];

export default function Sidebar() {
  const { t } = useLanguage();
  const { user, logout } = useAuth();

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1 className="sidebar-title">Renaissance</h1>
        <p className="sidebar-subtitle">by El Templo Labs</p>
      </div>

      <nav className="sidebar-nav">
        {navGroups.map((group) => (
          <div key={group.groupKey} className="sidebar-group">
            <span className="sidebar-group-label">{t(group.groupKey)}</span>
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
                >
                  <Icon size={18} />
                  <span>{t(item.labelKey)}</span>
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        {user && (
          <div className="sidebar-user">
            <span className="sidebar-user-name">{user.name}</span>
            <span className="sidebar-user-role">{user.role}</span>
          </div>
        )}
        <LanguageSelector />
        <button className="sidebar-logout" onClick={logout}>
          <LogOut size={16} />
          <span>Sign Out</span>
        </button>
      </div>
    </aside>
  );
}
