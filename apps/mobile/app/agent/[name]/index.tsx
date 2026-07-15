import { StyleSheet, View } from "react-native";
import PagerView from "react-native-pager-view";
import { AgentProvider } from "@/agent/AgentProvider";
import ChatPage from "@/agent/ChatPage";
import DashboardPage from "@/agent/DashboardPage";
import { AgentStackHeader } from "@/components/AgentHeader";

function AgentPages() {
  return (
    <View style={styles.screen}>
      <AgentStackHeader />
      <PagerView
        style={styles.pager}
        initialPage={0}
        orientation="horizontal"
        overdrag
      >
        <View key="chat" collapsable={false} style={styles.page}>
          <ChatPage />
        </View>
        <View key="dashboard" collapsable={false} style={styles.page}>
          <DashboardPage />
        </View>
      </PagerView>
    </View>
  );
}

export default function AgentScreen() {
  return (
    <AgentProvider>
      <AgentPages />
    </AgentProvider>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  pager: { flex: 1 },
  page: { flex: 1 },
});
