import Anthropic from '@anthropic-ai/sdk';

export interface ChronoEvent {
  type: 'text' | 'dispatch' | 'question';
  content: any;
}

export class ChronoClient {
  private client: Anthropic;
  private conversation: {role: 'user' | 'assistant'; content: string}[] = [];

  constructor(private systemPrompt: string, private model: string = 'claude-fable-5') {
    this.client = new Anthropic({
      apiKey: process.env.ANTHROPIC_API_KEY,
    });
  }

  async *send(userMessage: string): AsyncIterator<ChronoEvent> {
    this.conversation.push({role: 'user', content: userMessage});
    const response = await this.client.messages.create({
      model: this.model,
      system: this.systemPrompt,
      messages: this.conversation,
      max_tokens: 4096,
    });

    for (const block of response.content) {
      if (block.type === 'text') {
        this.conversation.push({role: 'assistant', content: block.text});
        yield {type: 'text', content: block.text};
      }
    }
  }
}
