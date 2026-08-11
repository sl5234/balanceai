import { useState } from 'react';
import { View, Text, ScrollView, Pressable } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { router } from 'expo-router';
import { useTheme } from '../theme';
import { Button, Icon } from '../components';

const STANDARD = [
  { name: 'Income statement', meta: 'August 2026 · accrual' },
  { name: 'Balance sheet', meta: 'As at 10 Aug 2026' },
  { name: 'Cash flow', meta: 'Rolling 90 days' },
];

const CUSTOM = [
  { name: 'Dining vs. groceries', meta: 'Yours · monthly' },
  { name: 'Software subscriptions', meta: 'Yours · quarterly' },
];

const ROWS = [
  { label: 'Revenue', value: '', weight: '600', indent: 0 },
  { label: 'Consulting', value: '9,400.00', weight: '400', indent: 14 },
  { label: 'Total revenue', value: '9,400.00', weight: '600', indent: 0 },
  { label: 'Expenses', value: '', weight: '600', indent: 0 },
  { label: 'Occupancy', value: '2,150.00', weight: '400', indent: 14 },
  { label: 'Dining', value: '412.60', weight: '400', indent: 14 },
  { label: 'Software', value: '486.00', weight: '400', indent: 14 },
  { label: 'Travel', value: '188.15', weight: '400', indent: 14 },
  { label: 'Total expenses', value: '3,236.75', weight: '600', indent: 0 },
  { label: 'Net income', value: '6,163.25', weight: '600', indent: 0 },
];

function ReportRow({ name, meta, onPress }) {
  const t = useTheme();
  return (
    <Pressable
      onPress={onPress}
      style={{ paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: t.rowHairline }}
    >
      <Text style={{ fontFamily: t.fontHeading, fontWeight: '600', fontSize: 17, color: t.text }}>{name}</Text>
      <Text style={{ fontFamily: t.fontBody, fontSize: 12, color: t.neutral[700], marginTop: 2 }}>{meta}</Text>
    </Pressable>
  );
}

export default function ReportsScreen() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const [openReport, setOpenReport] = useState(null);

  return (
    <View style={{ flex: 1, backgroundColor: t.bg }}>
      <View style={{ paddingTop: insets.top + 12, paddingHorizontal: 20, paddingBottom: 10 }}>
        <Text style={{ fontFamily: t.fontHeading, fontWeight: '600', fontSize: 19, letterSpacing: -0.4, color: t.text }}>
          Reports
        </Text>
      </View>

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: 16 }}>
        {openReport ? (
          <>
            <Pressable onPress={() => setOpenReport(null)} style={{ marginBottom: 10 }}>
              <Text style={{ fontFamily: t.fontBody, fontSize: 14, color: t.accent }}>← Reports</Text>
            </Pressable>
            <Text style={{ fontFamily: t.fontHeading, fontWeight: '600', fontSize: 26, letterSpacing: -0.5, color: t.text }}>
              {openReport.name}
            </Text>
            <Text style={{ fontFamily: t.fontBody, fontSize: 12, color: t.neutral[700], marginBottom: 14 }}>
              {openReport.meta}
            </Text>
            <View>
              {ROWS.map((r, i) => (
                <View
                  key={i}
                  style={{
                    flexDirection: 'row', justifyContent: 'space-between',
                    paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: t.rowHairline,
                  }}
                >
                  <Text style={{ fontFamily: t.fontBody, fontWeight: r.weight, fontSize: 14, color: t.text, paddingLeft: r.indent }}>
                    {r.label}
                  </Text>
                  <Text style={{ fontFamily: t.fontBody, fontWeight: r.weight, fontSize: 14, color: t.text, fontVariant: ['tabular-nums'] }}>
                    {r.value}
                  </Text>
                </View>
              ))}
            </View>
          </>
        ) : (
          <>
            <Text style={{ fontFamily: t.fontBody, fontSize: 10, letterSpacing: 1, textTransform: 'uppercase', color: t.neutral[700], paddingTop: 6, paddingBottom: 2 }}>
              Standard
            </Text>
            {STANDARD.map((r) => (
              <ReportRow key={r.name} name={r.name} meta={r.meta} onPress={() => setOpenReport(r)} />
            ))}

            <Text style={{ fontFamily: t.fontBody, fontSize: 10, letterSpacing: 1, textTransform: 'uppercase', color: t.neutral[700], paddingTop: 22, paddingBottom: 2 }}>
              Yours
            </Text>
            {CUSTOM.map((r) => (
              <ReportRow key={r.name} name={r.name} meta={r.meta} onPress={() => setOpenReport(r)} />
            ))}

            <Button
              variant="secondary"
              block
              style={{ marginTop: 18 }}
              onPress={() => router.push('/report-builder')}
              icon={<Icon name="plus-circle" size={18} color={t.accent} />}
            >
              New report
            </Button>
          </>
        )}
      </ScrollView>
    </View>
  );
}
