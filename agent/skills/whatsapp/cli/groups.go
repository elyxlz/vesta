package main

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/types"
)

// resolveGroup resolves an identifier to a group JID, returning an error if
// the identifier doesn't point to a group.
func (wac *WhatsAppClient) resolveGroup(identifier string) (types.JID, error) {
	jid, err := wac.ResolveRecipient(identifier)
	if err != nil {
		return types.JID{}, fmt.Errorf("Failed to resolve group: %v", err)
	}
	if jid.Server != types.GroupServer {
		return types.JID{}, fmt.Errorf("The specified identifier is not a WhatsApp group")
	}
	return jid, nil
}

func (wac *WhatsAppClient) CreateGroup(name string, participants []string) (bool, string) {
	if name == "" || len(participants) == 0 {
		return false, "Group name and participants are required"
	}

	jids, err := parseParticipantJIDs(participants)
	if err != nil {
		return false, err.Error()
	}

	resp, err := wac.client.CreateGroup(context.Background(), whatsmeow.ReqCreateGroup{
		Name:         name,
		Participants: jids,
	})
	if err != nil {
		return false, fmt.Sprintf("Failed to create group: %v", err)
	}
	if resp.JID.String() != "" {
		wac.store.StoreChat(resp.JID.String(), name, time.Now())
	}
	return true, fmt.Sprintf("Group '%s' created successfully", name)
}

func (wac *WhatsAppClient) LeaveGroup(groupIdentifier string) (bool, string) {
	if groupIdentifier == "" {
		return false, "Group name is required"
	}

	jid, err := wac.resolveGroup(groupIdentifier)
	if err != nil {
		return false, err.Error()
	}

	err = wac.client.LeaveGroup(context.Background(), jid)
	if err != nil {
		return false, fmt.Sprintf("Failed to leave group: %v", err)
	}
	return true, "Successfully left the group"
}

func (wac *WhatsAppClient) RenameGroup(groupIdentifier, newName string) (bool, string) {
	if groupIdentifier == "" || newName == "" {
		return false, "Group identifier and new name are required"
	}

	jid, err := wac.resolveGroup(groupIdentifier)
	if err != nil {
		return false, err.Error()
	}
	if err := wac.EnsureConnected(); err != nil {
		return false, err.Error()
	}

	if err := wac.client.SetGroupName(context.Background(), jid, newName); err != nil {
		return false, fmt.Sprintf("Failed to rename group: %v", err)
	}
	if err := wac.store.StoreChat(jid.String(), newName, time.Now()); err != nil {
		return false, fmt.Sprintf("Group renamed on WhatsApp but failed to update local store: %v", err)
	}
	return true, fmt.Sprintf("Group renamed to '%s'", newName)
}

func (wac *WhatsAppClient) SetGroupPhoto(groupIdentifier, filePath string) (bool, string) {
	if groupIdentifier == "" || filePath == "" {
		return false, "Group identifier and file path are required"
	}

	jid, err := wac.resolveGroup(groupIdentifier)
	if err != nil {
		return false, err.Error()
	}

	imageBytes, err := os.ReadFile(filePath)
	if err != nil {
		return false, fmt.Sprintf("Failed to read image file: %v", err)
	}
	if err := wac.EnsureConnected(); err != nil {
		return false, err.Error()
	}

	_, err = wac.client.SetGroupPhoto(context.Background(), jid, imageBytes)
	if err != nil {
		return false, fmt.Sprintf("Failed to set group photo: %v", err)
	}
	return true, "Group photo updated successfully"
}

func (wac *WhatsAppClient) SetGroupDescription(groupIdentifier, description string) (bool, string) {
	if groupIdentifier == "" || description == "" {
		return false, "Group identifier and description are required"
	}
	jid, err := wac.resolveGroup(groupIdentifier)
	if err != nil {
		return false, err.Error()
	}
	if err := wac.EnsureConnected(); err != nil {
		return false, err.Error()
	}
	if err := wac.client.SetGroupTopic(context.Background(), jid, "", "", description); err != nil {
		return false, fmt.Sprintf("Failed to set group description: %v", err)
	}
	return true, "Group description updated"
}

func (wac *WhatsAppClient) GetProfilePicture(jidStr, outputPath string) (bool, string) {
	if jidStr == "" || outputPath == "" {
		return false, "JID and output path are required"
	}
	jid, err := types.ParseJID(jidStr)
	if err != nil {
		// Try resolving as contact/group name
		resolved, resolveErr := wac.ResolveRecipient(jidStr)
		if resolveErr != nil {
			return false, fmt.Sprintf("Invalid JID and couldn't resolve: %v", err)
		}
		jid = resolved
	}
	if err := wac.EnsureConnected(); err != nil {
		return false, err.Error()
	}

	info, err := wac.client.GetProfilePictureInfo(context.Background(), jid, nil)
	if err != nil {
		return false, fmt.Sprintf("Failed to get profile picture: %v", err)
	}
	if info == nil || info.URL == "" {
		return false, "No profile picture set"
	}

	resp, err := http.Get(info.URL)
	if err != nil {
		return false, fmt.Sprintf("Failed to download picture: %v", err)
	}
	defer resp.Body.Close()

	f, err := os.Create(outputPath)
	if err != nil {
		return false, fmt.Sprintf("Failed to create file: %v", err)
	}
	defer f.Close()

	if _, err := io.Copy(f, resp.Body); err != nil {
		return false, fmt.Sprintf("Failed to write file: %v", err)
	}
	return true, fmt.Sprintf("Profile picture saved to %s", outputPath)
}

func (wac *WhatsAppClient) GetGroupInfo(groupIdentifier string) (map[string]any, error) {
	if groupIdentifier == "" {
		return nil, fmt.Errorf("group identifier is required")
	}
	jid, err := wac.resolveGroup(groupIdentifier)
	if err != nil {
		return nil, err
	}
	if err := wac.EnsureConnected(); err != nil {
		return nil, err
	}

	info, err := wac.client.GetGroupInfo(context.Background(), jid)
	if err != nil {
		return nil, fmt.Errorf("failed to get group info: %v", err)
	}

	participants := make([]map[string]any, 0, len(info.Participants))
	for _, p := range info.Participants {
		participants = append(participants, map[string]any{
			"jid":      p.JID.String(),
			"is_admin": p.IsAdmin,
		})
	}

	return map[string]any{
		"jid":          info.JID.String(),
		"name":         info.Name,
		"description":  info.Topic,
		"topic_id":     info.TopicID,
		"owner":        info.OwnerJID.String(),
		"created_at":   info.GroupCreated.String(),
		"participants":  participants,
		"is_locked":    info.IsLocked,
		"is_announce":  info.IsAnnounce,
	}, nil
}

func (wac *WhatsAppClient) GetGroupInviteLink(groupIdentifier string) (bool, string, string) {
	jid, err := wac.resolveGroup(groupIdentifier)
	if err != nil {
		return false, "", err.Error()
	}

	link, err := wac.client.GetGroupInviteLink(context.Background(), jid, false)
	if err != nil {
		return false, "", fmt.Sprintf("Failed to get invite link: %v", err)
	}
	return true, link, "Invite link retrieved successfully"
}

func (wac *WhatsAppClient) UpdateGroupParticipants(groupIdentifier, action string, participants []string) (bool, string) {
	if groupIdentifier == "" {
		return false, "group is required"
	}

	jid, err := wac.resolveGroup(groupIdentifier)
	if err != nil {
		return false, err.Error()
	}

	participantJIDs, err := parseParticipantJIDs(participants)
	if err != nil {
		return false, err.Error()
	}

	changeType, ok := map[string]whatsmeow.ParticipantChange{
		"add":     whatsmeow.ParticipantChangeAdd,
		"remove":  whatsmeow.ParticipantChangeRemove,
		"promote": whatsmeow.ParticipantChangePromote,
		"demote":  whatsmeow.ParticipantChangeDemote,
	}[action]
	if !ok {
		return false, "Invalid action: must be 'add', 'remove', 'promote', or 'demote'"
	}

	_, err = wac.client.UpdateGroupParticipants(context.Background(), jid, participantJIDs, changeType)
	if err != nil {
		return false, fmt.Sprintf("Failed to update participants: %v", err)
	}
	return true, fmt.Sprintf("Successfully %sed participants", action)
}

func parseParticipantJIDs(participants []string) ([]types.JID, error) {
	jids := make([]types.JID, 0, len(participants))
	for _, p := range participants {
		var jid types.JID
		var err error
		if strings.Contains(p, "@") {
			jid, err = types.ParseJID(p)
		} else {
			p = strings.TrimPrefix(p, "+")
			jid = types.NewJID(p, types.DefaultUserServer)
		}
		if err != nil {
			return nil, fmt.Errorf("invalid participant: %s", p)
		}
		jids = append(jids, jid)
	}
	return jids, nil
}
