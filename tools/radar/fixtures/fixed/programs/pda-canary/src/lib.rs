use anchor_lang::prelude::*;
use anchor_spl::token::{self, Token, TokenAccount, Transfer};

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod pda_canary_fixed {
    use super::*;

    pub fn drain_from_vault(ctx: Context<DrainFromVault>, amount: u64) -> Result<()> {
        let accounts = Transfer {
            from: ctx.accounts.vault.to_account_info(),
            to: ctx.accounts.recipient.to_account_info(),
            authority: ctx.accounts.authority.to_account_info(),
        };
        let signer_seeds: &[&[&[u8]]] = &[&[b"vault-authority", &[ctx.bumps.authority]]];
        token::transfer(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                accounts,
                signer_seeds,
            ),
            amount,
        )?;
        Ok(())
    }
}
#[derive(Accounts)]
pub struct DrainFromVault<'info> {
    #[account(mut)]
    pub vault: Account<'info, TokenAccount>,
    #[account(mut)]
    pub recipient: Account<'info, TokenAccount>,
    /// CHECK: constrained to the canonical program-derived authority.
    #[account(seeds = [b"vault-authority"], bump)]
    pub authority: UncheckedAccount<'info>,
    pub token_program: Program<'info, Token>,
}
