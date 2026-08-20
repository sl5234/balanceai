import { View, Text, ScrollView } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useTheme } from '../theme';
import { useLedger } from '../state/ledgerStore';
import { Tag } from '../components';

export default function LedgerScreen() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const { entries } = useLedger();

  return (
    <View style={{ flex: 1, backgroundColor: t.bg }}>
      <View style={{ paddingTop: insets.top + 12, paddingHorizontal: 20, paddingBottom: 10 }}>
        <Text style={{ fontFamily: t.fontHeading, fontWeight: '600', fontSize: 19, letterSpacing: -0.4, color: t.text }}>
          Ledger
        </Text>
      </View>

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: 16 }}>
        {entries.map((e, i) => (
          <View
            key={e.id}
            style={{
              paddingVertical: 15,
              borderBottomWidth: i < entries.length - 1 ? 1 : 0,
              borderBottomColor: t.rowHairline,
            }}
          >
            <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 10 }}>
              <Text style={{ flex: 1, fontFamily: t.fontHeading, fontWeight: '600', fontSize: 17, color: t.text }}>
                {e.merchant}
              </Text>
              <Text style={{ fontFamily: t.fontHeading, fontWeight: '600', fontSize: 17, color: t.text, fontVariant: ['tabular-nums'] }}>
                {e.amount}
              </Text>
            </View>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 6 }}>
              <Tag variant="accent">{e.category}</Tag>
              <Text style={{ fontFamily: t.fontBody, fontSize: 12, color: t.neutral[700] }}>{e.date} · {e.memo}</Text>
            </View>
          </View>
        ))}
      </ScrollView>
    </View>
  );
}
