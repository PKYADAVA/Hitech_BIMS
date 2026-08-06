import { Alert, Platform } from "react-native";

/**
 * Ask a yes/no question, on a phone or in a browser.
 *
 * `Alert.alert` is a no-op on React Native Web: nothing is shown and no button
 * handler ever runs. Every confirmation written with it therefore did nothing
 * at all in the browser — Log out among them, which is how this was found. The
 * screens are the same code on both, so the question has to be too.
 *
 * Returns a promise rather than taking a callback because that is the shape
 * both platforms can honestly implement: `window.confirm` is synchronous, the
 * native Alert is not, and awaiting hides the difference at the call site.
 *
 * Dismissing without choosing counts as "no". A confirmation exists to make
 * someone say yes on purpose.
 */
export function confirm({
  title,
  message,
  confirmLabel = "OK",
  cancelLabel = "Cancel",
  destructive = false,
}: {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
}): Promise<boolean> {
  if (Platform.OS === "web") {
    // The browser's own dialog carries no button labels of ours, so the title
    // and message have to say which action is about to happen on their own.
    const text = message ? `${title}\n\n${message}` : title;
    return Promise.resolve(
      typeof window !== "undefined" && typeof window.confirm === "function"
        ? window.confirm(text)
        : true
    );
  }

  return new Promise((resolve) => {
    Alert.alert(title, message, [
      { text: cancelLabel, style: "cancel", onPress: () => resolve(false) },
      {
        text: confirmLabel,
        style: destructive ? "destructive" : "default",
        onPress: () => resolve(true),
      },
    ], { cancelable: true, onDismiss: () => resolve(false) });
  });
}

/**
 * Tell someone something, on a phone or in a browser.
 *
 * Same gap as `confirm`: a one-button Alert shows nothing on web, so a message
 * meant to explain a refusal simply never appeared.
 */
export function notify(title: string, message?: string): void {
  if (Platform.OS === "web") {
    const text = message ? `${title}\n\n${message}` : title;
    if (typeof window !== "undefined" && typeof window.alert === "function") {
      window.alert(text);
    }
    return;
  }
  Alert.alert(title, message);
}
