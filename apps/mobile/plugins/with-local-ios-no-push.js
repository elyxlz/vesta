const {
  IOSConfig,
  withEntitlementsPlist,
  withXcodeProject,
} = require("expo/config-plugins");

const LOCAL_APPLE_TEAM_ID = "H78XNVF428";

module.exports = function withLocalIosNoPush(config) {
  config = withEntitlementsPlist(config, (modConfig) => {
    delete modConfig.modResults["aps-environment"];
    delete modConfig.modResults["com.apple.developer.associated-domains"];
    return modConfig;
  });

  return withXcodeProject(config, (modConfig) => {
    const project = modConfig.modResults;
    const targets = IOSConfig.Target.findSignableTargets(project);

    for (const [targetId, target] of targets) {
      const buildConfigurations =
        IOSConfig.XcodeUtils.getBuildConfigurationsForListId(
          project,
          target.buildConfigurationList,
        );

      for (const [, buildConfiguration] of buildConfigurations) {
        if (!buildConfiguration.buildSettings.PRODUCT_NAME) continue;

        buildConfiguration.buildSettings.DEVELOPMENT_TEAM = LOCAL_APPLE_TEAM_ID;
        buildConfiguration.buildSettings.CODE_SIGN_IDENTITY =
          '"Apple Development"';
        buildConfiguration.buildSettings.CODE_SIGN_STYLE = "Automatic";
      }

      for (const [key, projectEntry] of Object.entries(
        IOSConfig.XcodeUtils.getProjectSection(project),
      )) {
        if (!IOSConfig.XcodeUtils.isNotComment([key, projectEntry])) continue;

        projectEntry.attributes ??= {};
        projectEntry.attributes.TargetAttributes ??= {};
        projectEntry.attributes.TargetAttributes[targetId] ??= {};
        projectEntry.attributes.TargetAttributes[targetId].DevelopmentTeam =
          LOCAL_APPLE_TEAM_ID;
        projectEntry.attributes.TargetAttributes[targetId].ProvisioningStyle =
          "Automatic";
      }
    }

    return modConfig;
  });
};
