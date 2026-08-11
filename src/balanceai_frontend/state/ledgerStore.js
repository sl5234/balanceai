import { createContext, useContext, useState, useCallback } from 'react';

const SEED_ENTRIES = [
  { id: 'seed-1', merchant: 'Rent — 14th St', amount: '$2,150.00', category: 'Occupancy', date: '1 Aug', memo: 'August rent' },
  { id: 'seed-2', merchant: 'Nopa', amount: '$86.80', category: 'Dining', date: '6 Aug', memo: 'Dinner, two' },
  { id: 'seed-3', merchant: 'Figma', amount: '$45.00', category: 'Software', date: '5 Aug', memo: 'Monthly seat' },
  { id: 'seed-4', merchant: 'Blue Bottle', amount: '$14.20', category: 'Dining', date: '4 Aug', memo: 'Coffee' },
  { id: 'seed-5', merchant: 'Caltrain', amount: '$9.75', category: 'Travel', date: '3 Aug', memo: 'SF → Palo Alto' },
];

const LedgerContext = createContext(null);

export function LedgerProvider({ children }) {
  const [entries, setEntries] = useState(SEED_ENTRIES);

  const addEntry = useCallback((entry) => {
    setEntries((prev) => [{ id: `entry-${Date.now()}`, ...entry }, ...prev]);
  }, []);

  return (
    <LedgerContext.Provider value={{ entries, addEntry }}>
      {children}
    </LedgerContext.Provider>
  );
}

export const useLedger = () => useContext(LedgerContext);
