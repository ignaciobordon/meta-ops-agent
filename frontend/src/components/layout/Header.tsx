import { useEffect, useState } from 'react';
import { Power, AlertTriangle } from 'lucide-react';
import { useStore } from '../../store';
import { organizationsApi } from '../../services/api';
import './Header.css';

export default function Header() {
  const { currentOrg, setCurrentOrg } = useStore();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // Load first org on mount
    organizationsApi.list().then((res) => {
      if (res.data.length > 0 && !currentOrg) {
        setCurrentOrg(res.data[0]);
      }
    });
  }, [currentOrg, setCurrentOrg]);

  const toggleOperatorArmed = async () => {
    if (!currentOrg) return;
    setLoading(true);
    try {
      const res = await organizationsApi.toggleOperatorArmed(
        currentOrg.id,
        !currentOrg.operator_armed
      );
      setCurrentOrg(res.data);
    } catch (error) {
      console.error('Failed to toggle Operator Armed:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <header className="header">
      <div className="header-left">
        <div className="workspace-switcher">
          <span className="workspace-label">Workspace:</span>
          <span className="workspace-name">{currentOrg?.name || 'Loading...'}</span>
        </div>
      </div>

      <div className="header-right">
        <button
          onClick={toggleOperatorArmed}
          disabled={loading}
          className={`operator-toggle ${currentOrg?.operator_armed ? 'armed' : ''}`}
        >
          {currentOrg?.operator_armed ? (
            <>
              <AlertTriangle size={16} />
              <span>LIVE MODE</span>
            </>
          ) : (
            <>
              <Power size={16} />
              <span>Dry Run</span>
            </>
          )}
        </button>
      </div>
    </header>
  );
}
