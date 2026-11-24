async function answerWorkspaceDialog(page, action, text) {
  const dialog=page.locator('.workspace-dialog[open]');
  if(text!==undefined)await dialog.locator('input').fill(text);
  await dialog.locator(`button[value="${action}"]`).click();
}

module.exports={answerWorkspaceDialog};
