import { useRef, useState } from 'react';
import { View, Text, Pressable, Modal, Image } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { useTheme } from '../../theme';

const GROUND = '#141312';
const PAPER = '#f3f2f2';

export function CameraOverlay({ visible, onClose, onUsePhoto }) {
  const t = useTheme();
  const insets = useSafeAreaInsets();
  const cameraRef = useRef(null);
  const [permission, requestPermission] = useCameraPermissions();
  const [capturedUri, setCapturedUri] = useState(null);

  const close = () => {
    setCapturedUri(null);
    onClose();
  };

  const shoot = async () => {
    if (!cameraRef.current) return;
    const photo = await cameraRef.current.takePictureAsync();
    setCapturedUri(photo.uri);
  };

  const usePhoto = () => {
    onUsePhoto(capturedUri);
    setCapturedUri(null);
  };

  const retake = () => setCapturedUri(null);

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="fullScreen" onRequestClose={close}>
      <View style={{ flex: 1, backgroundColor: GROUND }}>
        <View style={{ paddingTop: Math.max(insets.top, 16), paddingHorizontal: 18 }}>
          <Pressable onPress={close}>
            <Text style={{ color: PAPER, fontFamily: t.fontBody, fontSize: 15 }}>← Chat</Text>
          </Pressable>
        </View>

        {capturedUri ? (
          <>
            <View style={{ flex: 1, margin: 14, marginHorizontal: 18, overflow: 'hidden' }}>
              <Image source={{ uri: capturedUri }} style={{ flex: 1 }} resizeMode="cover" />
            </View>
            <View style={{ flexDirection: 'row', gap: 12, paddingHorizontal: 18, paddingBottom: Math.max(insets.bottom, 32) }}>
              <Pressable
                onPress={retake}
                style={{ flex: 1, paddingVertical: 14, alignItems: 'center', borderWidth: 1, borderColor: 'rgba(243,242,242,0.4)', borderRadius: t.radius.md }}
              >
                <Text style={{ color: PAPER, fontFamily: t.fontHeading, fontWeight: '600', fontSize: 14 }}>Retake</Text>
              </Pressable>
              <Pressable
                onPress={usePhoto}
                style={{ flex: 1, paddingVertical: 14, alignItems: 'center', backgroundColor: t.accent, borderRadius: t.radius.md }}
              >
                <Text style={{ color: t.bg, fontFamily: t.fontHeading, fontWeight: '600', fontSize: 14 }}>Use Photo</Text>
              </Pressable>
            </View>
          </>
        ) : !permission ? (
          <View style={{ flex: 1 }} />
        ) : !permission.granted ? (
          <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 32, gap: 16 }}>
            <Text style={{ color: PAPER, fontFamily: t.fontBody, fontSize: 15, textAlign: 'center', lineHeight: 22 }}>
              {permission.canAskAgain
                ? "BalanceAI needs camera access to capture receipts."
                : 'Camera access was denied. Enable it for BalanceAI in your device settings to capture receipts.'}
            </Text>
            {permission.canAskAgain && (
              <Pressable
                onPress={requestPermission}
                style={{ paddingVertical: 12, paddingHorizontal: 24, backgroundColor: t.accent, borderRadius: t.radius.md }}
              >
                <Text style={{ color: t.bg, fontFamily: t.fontHeading, fontWeight: '600', fontSize: 14 }}>Grant Access</Text>
              </Pressable>
            )}
          </View>
        ) : (
          <>
            <View style={{
              flex: 1, margin: 14, marginHorizontal: 18,
              borderWidth: 1, borderColor: 'rgba(243,242,242,0.35)',
              overflow: 'hidden',
            }}>
              <CameraView ref={cameraRef} style={{ flex: 1 }} facing="back" />
            </View>

            <View style={{ paddingHorizontal: 18, paddingBottom: Math.max(insets.bottom, 44), alignItems: 'center' }}>
              <Pressable
                onPress={shoot}
                style={{
                  width: 66, height: 66, borderRadius: 33,
                  backgroundColor: PAPER,
                  borderWidth: 4, borderColor: 'rgba(243,242,242,0.4)',
                }}
              />
            </View>
          </>
        )}
      </View>
    </Modal>
  );
}
