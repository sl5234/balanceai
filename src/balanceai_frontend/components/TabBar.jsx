import { useEffect, useState } from 'react';
import { View, Text, Pressable, Keyboard } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '../theme';
import { Icon } from './Icon';

const TABS = [
  { id: 'chat', label: 'Chat', icon: 'chat' },
  { id: 'ledger', label: 'Ledger', icon: 'ledger' },
  { id: 'reports', label: 'Reports', icon: 'reports' },
];

export function TabBar({ current, onChange }) {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    const showSub = Keyboard.addListener('keyboardDidShow', () => setHidden(true));
    const hideSub = Keyboard.addListener('keyboardDidHide', () => setHidden(false));
    return () => {
      showSub.remove();
      hideSub.remove();
    };
  }, []);

  if (hidden) return null;

  return (
    <View style={{
      flexDirection: 'row',
      paddingTop: 6,
      paddingHorizontal: 14,
      paddingBottom: Math.max(insets.bottom, 4),
      borderTopWidth: 1,
      borderTopColor: t.divider,
      backgroundColor: t.bg,
    }}>
      {TABS.map((tab) => {
        const active = current === tab.id;
        const color = active ? t.accent : t.neutral[600];
        return (
          <Pressable
            key={tab.id}
            onPress={() => onChange(tab.id)}
            style={{ flex: 1, alignItems: 'center', gap: 2, paddingVertical: 5 }}
          >
            <Icon name={tab.icon} size={23} color={color} />
            <Text style={{ fontFamily: t.fontHeading, fontWeight: '600', fontSize: 10.5, letterSpacing: 0.2, color }}>
              {tab.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}
