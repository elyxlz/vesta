import {
  useOpenProviderStep,
  useProviderResource,
} from "@/agent/settings/provider-actions";
import { useProviderDraft } from "@/agent/settings/provider-draft";
import {
  ProviderChoiceList,
  ProviderStepScreen,
} from "@/agent/settings/provider-steps";
import { FormSectionSkeleton } from "@/components/ui/form-section-skeleton";

export default function ProviderChooseScreen() {
  const { resource } = useProviderResource();
  const { start } = useProviderDraft();
  const openStep = useOpenProviderStep();
  const catalog = resource.data?.catalog;
  return (
    <ProviderStepScreen title="Choose a provider">
      {catalog ? (
        <ProviderChoiceList
          catalog={catalog}
          onPick={(kind) => {
            start(kind);
            openStep("sign-in");
          }}
        />
      ) : (
        <FormSectionSkeleton rows={5} label="Loading providers" />
      )}
    </ProviderStepScreen>
  );
}
