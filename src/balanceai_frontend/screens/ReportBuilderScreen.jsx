import { useState } from 'react';
import { View, Text, ScrollView, Pressable } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { router } from 'expo-router';
import { useTheme } from '../theme';
import { TextField, Button, Tag } from '../components';

const ALL_METRICS = ['revenue', 'expenses', 'net_income', 'cash', 'ar', 'ap', 'assets', 'liabilities', 'equity', 'burn_rate', 'runway'];
const DATE_RANGES = ['week', 'month', 'quarter', 'year'];
const CHART_TYPES = [['bar', 'Bar'], ['line', 'Line'], ['table', 'Table']];

function Segmented({ options, value, onChange }) {
  const t = useTheme();
  return (
    <View style={{ flexDirection: 'row', borderWidth: 1, borderColor: t.divider, borderRadius: t.radius.md, overflow: 'hidden' }}>
      {options.map(([id, label], i) => {
        const active = value === id;
        return (
          <Pressable
            key={id}
            onPress={() => onChange(id)}
            style={{
              flex: 1, paddingVertical: 8, alignItems: 'center',
              backgroundColor: active ? t.accent : 'transparent',
              borderLeftWidth: i > 0 ? 1 : 0, borderLeftColor: t.divider,
            }}
          >
            <Text style={{ fontFamily: t.fontBody, fontSize: 13, color: active ? t.bg : t.text }}>{label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function FieldLabel({ children }) {
  const t = useTheme();
  return (
    <Text style={{ fontFamily: t.fontBody, fontSize: 10, letterSpacing: 1, textTransform: 'uppercase', color: t.neutral[700], marginBottom: 7 }}>
      {children}
    </Text>
  );
}

export default function ReportBuilderScreen() {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const [name, setName] = useState('');
  const [range, setRange] = useState('month');
  const [metrics, setMetrics] = useState(['revenue', 'net_income']);
  const [chartType, setChartType] = useState('bar');

  const toggle = (m) => setMetrics((s) => (s.includes(m) ? s.filter((x) => x !== m) : [...s, m]));

  return (
    <View style={{ flex: 1, backgroundColor: t.bg }}>
      <View style={{ paddingTop: insets.top + 12, paddingHorizontal: 20, paddingBottom: 10 }}>
        <Pressable onPress={() => router.back()} style={{ marginBottom: 6 }}>
          <Text style={{ fontFamily: t.fontBody, fontSize: 14, color: t.accent }}>← Reports</Text>
        </Pressable>
        <Text style={{ fontFamily: t.fontHeading, fontWeight: '600', fontSize: 19, letterSpacing: -0.4, color: t.text }}>
          Report builder
        </Text>
      </View>

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: 30, gap: 18 }}>
        <View>
          <FieldLabel>Report name</FieldLabel>
          <TextField placeholder="e.g. Q1 profitability analysis" value={name} onChangeText={setName} />
        </View>

        <View>
          <FieldLabel>Date range</FieldLabel>
          <Segmented options={DATE_RANGES.map((r) => [r, r[0].toUpperCase() + r.slice(1)])} value={range} onChange={setRange} />
        </View>

        <View>
          <FieldLabel>Visualization</FieldLabel>
          <Segmented options={CHART_TYPES} value={chartType} onChange={setChartType} />
        </View>

        <View>
          <FieldLabel>Select metrics</FieldLabel>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
            {ALL_METRICS.map((m) => {
              const active = metrics.includes(m);
              return (
                <Pressable key={m} onPress={() => toggle(m)}>
                  <Tag variant={active ? 'accent' : 'outline'}>{m.replace(/_/g, ' ')}</Tag>
                </Pressable>
              );
            })}
          </View>
        </View>

        <View style={{ height: 1, backgroundColor: t.divider }} />
        <Button block onPress={() => router.back()}>Generate report</Button>
      </ScrollView>
    </View>
  );
}
