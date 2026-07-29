import { NativeStackScreenProps } from "@react-navigation/native-stack";
import React, { useLayoutEffect, useMemo, useState } from "react";
import { Alert, Text, View } from "react-native";

import { extractPlaceholders, sendTemplate } from "@/api/sms";
import { KeyboardAwareScrollView } from "@/components/KeyboardAwareScrollView";
import { Button, Card, Field } from "@/components/ui";
import { ModuleStackParams } from "@/navigation/types";
import { queryClient } from "@/query/queryClient";
import { makeStyles, spacing, type } from "@/theme";

type Props = NativeStackScreenProps<ModuleStackParams, "SmsSend">;

export function SmsSendScreen({ route, navigation }: Props) {
  const styles = useStyles();
  const template = route.params.row;
  const templateId = template.id;
  const body = String(template.body ?? "");
  const placeholders = useMemo(() => extractPlaceholders(body), [body]);

  const [phone, setPhone] = useState("");
  const [partyName, setPartyName] = useState("");
  const [vars, setVars] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);

  useLayoutEffect(() => {
    navigation.setOptions({ title: "Send SMS" });
  }, [navigation]);

  const preview = useMemo(
    () => body.replace(/\{(\w+)\}/g, (_m, k) => (vars[k] ? vars[k] : `{${k}}`)),
    [body, vars]
  );

  const onSend = async () => {
    if (!phone.trim()) {
      Alert.alert("Phone required", "Enter a mobile number to send to.");
      return;
    }
    setSending(true);
    try {
      const res = await sendTemplate(templateId, {
        phone: phone.trim(),
        party_name: partyName.trim() || undefined,
        context: vars,
      });
      queryClient.invalidateQueries({ queryKey: ["list", "/sms/messages/"] });
      // Refresh the Home dashboard KPIs so "SMS sent · today" reflects this send.
      queryClient.invalidateQueries({ queryKey: ["stats-overview"] });
      if (res.sent) {
        Alert.alert("Sent ✓", `Status: ${res.status}`, [
          { text: "OK", onPress: () => navigation.goBack() },
        ]);
      } else {
        Alert.alert("Not sent", res.error || `Status: ${res.status}`);
      }
    } catch (e) {
      Alert.alert("Failed", (e as Error)?.message ?? "Could not send SMS.");
    } finally {
      setSending(false);
    }
  };

  return (
    <KeyboardAwareScrollView style={styles.screen} contentContainerStyle={styles.content}>
        <Card style={{ marginBottom: spacing.lg }}>
          <Text style={styles.tplName}>{String(template.name ?? template.key ?? "Template")}</Text>
          <Text style={styles.preview}>{preview}</Text>
          <Text style={styles.count}>{preview.length} chars</Text>
        </Card>

        <Field
          label="Mobile number"
          value={phone}
          onChangeText={setPhone}
          placeholder="9876543210"
          keyboardType="phone-pad"
        />
        <Field label="Recipient name (optional)" value={partyName} onChangeText={setPartyName} placeholder="e.g. Ramesh" />

        {placeholders.length > 0 ? (
          <Text style={styles.section}>Placeholders</Text>
        ) : null}
        {placeholders.map((p) => (
          <Field
            key={p}
            label={p}
            value={vars[p] ?? ""}
            onChangeText={(v) => setVars((prev) => ({ ...prev, [p]: v }))}
            placeholder={`Value for {${p}}`}
          />
        ))}

        <Button title="Send SMS" onPress={onSend} loading={sending} />
        <View style={{ height: spacing.xxl }} />
    </KeyboardAwareScrollView>
  );
}

const useStyles = makeStyles((colors) => ({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md },
  tplName: { ...type.h3, color: colors.text, marginBottom: spacing.xs },
  preview: { ...type.body, color: colors.text, lineHeight: 22 },
  count: { ...type.caption, color: colors.textFaint, marginTop: spacing.sm },
  section: { ...type.label, color: colors.textMuted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: spacing.sm },
}));
