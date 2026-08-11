import { useState } from 'react';
import { View, Text, Pressable, ScrollView } from 'react-native';
import { router } from 'expo-router';
import { useTheme } from '../theme';
import { TextField, Button } from '../components';

function FieldLabel({ children }) {
  const t = useTheme();
  return (
    <Text style={{ fontFamily: t.fontBody, fontSize: 10, letterSpacing: 1, textTransform: 'uppercase', color: t.neutral[700], marginBottom: 7 }}>
      {children}
    </Text>
  );
}

export default function LoginScreen() {
  const t = useTheme();
  const [email, setEmail] = useState('');
  const [pass, setPass] = useState('');
  const [loading, setLoading] = useState(false);

  const handleLogin = () => {
    setLoading(true);
    setTimeout(() => {
      setLoading(false);
      router.replace('/(tabs)/');
    }, 1400);
  };

  return (
    <View style={{ flex: 1, backgroundColor: t.bg }}>
      <ScrollView
        contentContainerStyle={{ flexGrow: 1, justifyContent: 'center' }}
        keyboardShouldPersistTaps="handled"
      >
        <View style={{ paddingHorizontal: 28, gap: 14 }}>

          <View style={{ alignItems: 'center', marginBottom: 48 }}>
            <Text style={{ fontFamily: t.fontHeading, fontWeight: '600', fontSize: 40, letterSpacing: -1 }}>
              <Text style={{ color: t.accent }}>Balance</Text>
              <Text style={{ color: t.accent2 }}>AI</Text>
            </Text>
            <View style={{ width: 60, height: 1, backgroundColor: t.text, marginTop: 16 }} />
            <View style={{ width: 60, height: 1, backgroundColor: t.divider, marginTop: 2 }} />
          </View>

          <View>
            <FieldLabel>Email</FieldLabel>
            <TextField
              placeholder="you@example.com"
              value={email}
              onChangeText={setEmail}
              keyboardType="email-address"
              autoCapitalize="none"
            />
          </View>

          <View>
            <FieldLabel>Password</FieldLabel>
            <TextField placeholder="••••••••••••" value={pass} onChangeText={setPass} secureTextEntry />
          </View>

          <Pressable style={{ alignSelf: 'flex-end' }}>
            <Text style={{ fontFamily: t.fontBody, fontSize: 13, color: t.accent }}>Reset access</Text>
          </Pressable>

          <Button variant="primary" block onPress={handleLogin} style={{ marginTop: 4 }}>
            {loading ? 'Signing in…' : 'Sign in'}
          </Button>

          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 4 }}>
            <View style={{ flex: 1, height: 1, backgroundColor: t.divider }} />
            <Text style={{ fontFamily: t.fontBody, fontSize: 12, color: t.neutral[700] }}>or</Text>
            <View style={{ flex: 1, height: 1, backgroundColor: t.divider }} />
          </View>

          <Pressable
            onPress={handleLogin}
            style={({ pressed }) => ({
              backgroundColor: pressed ? 'rgba(32,30,29,0.07)' : t.surface,
              borderWidth: 1, borderColor: t.divider, borderRadius: t.radius.md,
              paddingVertical: 13, alignItems: 'center',
            })}
          >
            <Text style={{ fontFamily: t.fontBody, fontSize: 14, color: t.text }}>Use Face ID or Touch ID</Text>
          </Pressable>

        </View>
      </ScrollView>
    </View>
  );
}
